"""Open-Meteo hourly forecasts for many points, batched, deduplicated and cached.

Budget strategy (RESEARCH §3), the free tier being the binding constraint:

1. **Snap** every requested point to a 0.05° grid cell (~3.5 mi, about the resolution of the HRRR
   model that drives US short-range forecasts). Checkpoints on three routes sharing an interstate,
   and heatmap grid points, collapse onto the same cells.
2. **Cache per (cell, UTC date)** for 30 minutes, so changing the departure time or re-planning
   reuses everything already fetched, and only missing days are requested.
3. **Batch**: cells needing the same date range share one POST (form body, so no URL-length
   limit), in chunks of ``CHUNK_SIZE`` locations, a few chunks in parallel.
4. **Partial failure is not total failure**: if a chunk fails after retries, its cells are
   reported as missing (checkpoints show "no forecast") instead of failing the whole plan, unless
   *every* chunk failed.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from django.conf import settings
from django.core.cache import cache

from ..domain.forecast import HourlySeries
from ..domain.types import LatLon
from .http import UpstreamError, request_json

logger = logging.getLogger(__name__)

CELL_DEG = 0.05
CHUNK_SIZE = 150
# Open-Meteo counts each location as one call (600/min free); wider bursts hit HTTP 429.
MAX_PARALLEL_CHUNKS = 2
CACHE_TTL_S = 30 * 60
HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
FREE_URL = "https://api.open-meteo.com/v1/forecast"
COMMERCIAL_URL = "https://customer-api.open-meteo.com/v1/forecast"

Cell = tuple[int, int]
# One cached day: 24 hourly rows per variable, in row order starting at 00:00 UTC.
DayRows = dict[str, list[float | None]]


def cell_of(p: LatLon) -> Cell:
    return (round(p.lat / CELL_DEG), round(p.lon / CELL_DEG))


def cell_center(c: Cell) -> LatLon:
    return LatLon(round(c[0] * CELL_DEG, 4), round(c[1] * CELL_DEG, 4))


def utc_dates(start: float, end: float) -> list[date]:
    d0 = datetime.fromtimestamp(start, timezone.utc).date()
    d1 = datetime.fromtimestamp(end, timezone.utc).date()
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def _day_start(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


@dataclass
class WeatherBatch:
    """Hourly series for every requested cell, plus cells whose forecast could not be fetched."""

    series: dict[Cell, HourlySeries] = field(default_factory=dict)
    missing: set[Cell] = field(default_factory=set)
    upstream_calls: int = 0  # HTTP requests made (0 when fully cached)
    locations_fetched: int = 0

    def at(self, p: LatLon) -> HourlySeries | None:
        return self.series.get(cell_of(p))


class OpenMeteoProvider:
    service = "weather"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else settings.TRIPS["OPEN_METEO_API_KEY"]
        self.url = COMMERCIAL_URL if self.api_key else FREE_URL
        self._last_error: str | None = None

    def hourly(self, points: Iterable[LatLon], start: float, end: float) -> WeatherBatch:
        """Hourly forecasts covering [start, end] (epoch s) for each point's grid cell."""
        if end < start:
            raise ValueError("end must not be before start")
        cells = sorted({cell_of(p) for p in points})
        dates = utc_dates(start, end)
        batch = WeatherBatch()

        # 1. Cache lookup per (cell, date); group cells by the date range they still need.
        days: dict[Cell, dict[date, DayRows]] = defaultdict(dict)
        need: dict[tuple[date, date], list[Cell]] = defaultdict(list)
        keys = {(c, d): _cache_key(c, d) for c in cells for d in dates}
        cached = cache.get_many(list(keys.values()))
        for c in cells:
            missing_dates = []
            for d in dates:
                rows = cached.get(keys[(c, d)])
                if rows is None:
                    missing_dates.append(d)
                else:
                    days[c][d] = rows
            if missing_dates:
                need[(missing_dates[0], missing_dates[-1])].append(c)

        # 2. Fetch what's missing, in chunks, a few in parallel.
        jobs = [
            (rng, group[i : i + CHUNK_SIZE])
            for rng, group in need.items()
            for i in range(0, len(group), CHUNK_SIZE)
        ]
        if jobs:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as pool:
                results = list(pool.map(lambda job: self._fetch_chunk(*job), jobs))
            failures = 0
            to_cache: dict[str, DayRows] = {}
            for (_rng, chunk), result in zip(jobs, results, strict=True):
                batch.upstream_calls += 1
                if result is None:
                    failures += 1
                    batch.missing.update(chunk)
                    continue
                batch.locations_fetched += len(chunk)
                for c, per_day in result.items():
                    for d, rows in per_day.items():
                        days[c][d] = rows
                        to_cache[_cache_key(c, d)] = rows
            if to_cache:
                cache.set_many(to_cache, CACHE_TTL_S)
            if failures == len(jobs):
                raise UpstreamError(
                    self.service, self._last_error or "forecast service unavailable"
                )

        # 3. Assemble contiguous hourly series per cell.
        for c in cells:
            if c in batch.missing:
                continue
            per_day = days.get(c, {})
            if any(d not in per_day for d in dates):
                batch.missing.add(c)
                continue
            batch.series[c] = _assemble(per_day, dates)
        return batch

    def _fetch_chunk(
        self, date_range: tuple[date, date], chunk: list[Cell]
    ) -> dict[Cell, dict[date, DayRows]] | None:
        centers = [cell_center(c) for c in chunk]
        form: dict[str, Any] = {
            "latitude": ",".join(f"{p.lat:.4f}" for p in centers),
            "longitude": ",".join(f"{p.lon:.4f}" for p in centers),
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",  # also converts snowfall to inches (verified)
            "timeformat": "unixtime",
            "timezone": "GMT",
            "start_date": date_range[0].isoformat(),
            "end_date": date_range[1].isoformat(),
        }
        if self.api_key:
            form["apikey"] = self.api_key
        try:
            body = request_json("POST", self.url, service=self.service, data=form)
            return parse_open_meteo(body, chunk, date_range)
        except UpstreamError as exc:
            logger.warning("weather chunk of %d cells failed: %s", len(chunk), exc)
            self._last_error = (
                "weather service rate limit reached; please retry in a minute"
                if exc.status == 429
                else str(exc)
            )
            return None


def parse_open_meteo(
    body: Any, chunk: list[Cell], date_range: tuple[date, date]
) -> dict[Cell, dict[date, DayRows]]:
    """Split an Open-Meteo multi-location response into per-cell, per-UTC-day rows."""
    locations = body if isinstance(body, list) else [body]  # a single location is not wrapped
    if len(locations) != len(chunk):
        raise UpstreamError("weather", f"expected {len(chunk)} locations, got {len(locations)}")
    n_days = (date_range[1] - date_range[0]).days + 1
    out: dict[Cell, dict[date, DayRows]] = {}
    for c, loc in zip(chunk, locations, strict=True):
        hourly = loc.get("hourly") or {}
        times = hourly.get("time") or []
        index = {int(t): i for i, t in enumerate(times)}
        wind, gust = _column(hourly, "wind_speed_10m"), _column(hourly, "wind_gusts_10m")
        rain, showers = _column(hourly, "rain"), _column(hourly, "showers")
        snow = _column(hourly, "snowfall")
        per_day: dict[date, DayRows] = {}
        for k in range(n_days):
            d = date_range[0] + timedelta(days=k)
            rows: DayRows = {"wind": [], "gust": [], "rain": [], "snow": []}
            t0 = _day_start(d)
            for h in range(24):
                i = index.get(t0 + h * 3600)
                if i is None:
                    for v in rows.values():
                        v.append(None)
                    continue
                rows["wind"].append(_num(wind[i]))
                rows["gust"].append(_num(gust[i]))
                r, s = _num(rain[i]), _num(showers[i])
                rows["rain"].append(None if r is None and s is None else (r or 0.0) + (s or 0.0))
                rows["snow"].append(_num(snow[i]))
            per_day[d] = rows
        out[c] = per_day
    return out


def _column(hourly: dict[str, Any], name: str) -> list[Any]:
    """A variable's values, or all-None if the API omitted it."""
    return hourly.get(name) or [None] * len(hourly.get("time") or [])


def _num(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _assemble(per_day: dict[date, DayRows], dates: list[date]) -> HourlySeries:
    times: list[int] = []
    cols: dict[str, list[float | None]] = {"wind": [], "gust": [], "rain": [], "snow": []}
    for d in dates:
        t0 = _day_start(d)
        times.extend(t0 + h * 3600 for h in range(24))
        for k in cols:
            cols[k].extend(per_day[d][k])
    return HourlySeries(
        times=tuple(times),
        wind_mph=tuple(cols["wind"]),
        gust_mph=tuple(cols["gust"]),
        rain_in_hr=tuple(cols["rain"]),
        snow_in_hr=tuple(cols["snow"]),
    )


def _cache_key(c: Cell, d: date) -> str:
    return f"wx:{c[0]}:{c[1]}:{d.isoformat()}"
