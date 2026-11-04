"""Trip planning: the orchestration between providers and the pure domain logic.

    routes (routing API)
      → checkpoints every N mi with truck ETAs                     domain.sampling
      → corridor grid for the heatmap                              domain.corridor
      → ONE batched weather fetch for checkpoints + grid           providers.weather
      → weather at each checkpoint's ETA → risk (incl. load)       domain.forecast / domain.risk
      → summaries → ranking → recommendation reason                domain.scoring
      → heatmap frames for hours 0–48 after departure

The output is a JSON-ready dict (see ``docs/PLAN.md`` §1 for the contract). Providers are
injected so tests and demo mode can substitute fakes.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings

from ..domain.corridor import build_corridor_grid
from ..domain.forecast import weather_at
from ..domain.geo import haversine_mi, simplify
from ..domain.hos import Stop, hos_schedule, make_drive_to_clock
from ..domain.risk import classify, classify_values
from ..domain.sampling import (
    DriveToClock,
    identity_clock,
    place_checkpoints,
    point_at_drive_time,
    route_duration_s,
)
from ..domain.scoring import (
    deciding_criterion,
    rank,
    recommendation_reason,
    summarize,
    why_not_chosen,
)
from ..domain.types import Checkpoint, LatLon, RiskLevel, RoutePath, RouteSummary
from ..providers.demo import FixtureRouting, StormScenarioWeather
from ..providers.http import UpstreamError
from ..providers.routing import NoRouteError, OsrmProvider, RoutingProvider
from ..providers.weather import OpenMeteoProvider, WeatherBatch

logger = logging.getLogger(__name__)

HEATMAP_HOURS = 48
DEPARTURE_SCAN_OFFSETS_H = (0, 3, 6, 9, 12, 18, 24)  # extra E4
MAX_ROUTE_MILES = 3000
MIN_TRIP_MILES = 1.0
FORECAST_HORIZON_S = 15 * 86400  # Open-Meteo serves 16 days; keep a day of margin
LOW_CONFIDENCE_AFTER_S = 72 * 3600
DISPLAY_SIMPLIFY_DEG = 1.5e-4  # ~15 m: invisible at any useful zoom, ~85% fewer points
ROUTE_NAMES = ("Route A", "Route B", "Route C")


class WeatherProvider(Protocol):
    def hourly(self, points: Iterable[LatLon], start: float, end: float) -> WeatherBatch: ...


class PlanError(Exception):
    """A request that is valid in shape but can't be planned (maps to HTTP 422)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PlanRequest:
    origin: LatLon
    destination: LatLon
    departure: float  # epoch seconds (UTC)
    load_lb: float
    interval_mi: int
    origin_label: str = ""
    destination_label: str = ""
    simulate_storm: bool = False  # extra E3: synthetic storm instead of the real forecast
    hos: bool = False  # extra E5: include Hours-of-Service breaks in ETAs


@dataclass
class _RouteWork:
    name: str
    path: RoutePath
    checkpoints: list[Checkpoint]
    duration_s: float
    clock: DriveToClock = identity_clock  # driving seconds -> clock seconds (E5 breaks)
    stops: list[Stop] = dataclasses.field(default_factory=list)
    summary: RouteSummary | None = None


SIMULATED_WARNING = (
    "Weather is SIMULATED (demo storm scenario) — not a real forecast. "
    "Turn off 'Simulate a storm' for live forecasts."
)


def default_providers() -> tuple[RoutingProvider, WeatherProvider]:
    return OsrmProvider(), OpenMeteoProvider()


def providers_for(req: PlanRequest) -> tuple[RoutingProvider, WeatherProvider]:
    """Live providers, adjusted for demo mode (recorded routes) and the storm simulation."""
    routing, weather = default_providers()
    if settings.TRIPS["DEMO_MODE"]:
        routing = FixtureRouting(routing)
    if req.simulate_storm:
        weather = StormScenarioWeather(req.origin, req.destination, req.departure)
    return routing, weather


def plan_trip(
    req: PlanRequest,
    routing: RoutingProvider | None = None,
    weather: WeatherProvider | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if routing is None or weather is None:
        routing, weather = providers_for(req)
    now = time.time() if now is None else now
    speed_cap = float(settings.TRIPS["TRUCK_SPEED_CAP_MPH"])

    if haversine_mi(req.origin, req.destination) < MIN_TRIP_MILES:
        raise PlanError("same_place", "Origin and destination are the same place.")

    # 1. Routes ------------------------------------------------------------------------------
    try:
        paths = routing.routes(req.origin, req.destination)
    except NoRouteError as exc:
        raise PlanError("no_route", "No drivable route was found between these places.") from exc
    if not paths:
        raise PlanError("no_route", "No drivable route was found between these places.")
    longest = max(p.distance_mi for p in paths)
    if min(p.distance_mi for p in paths) > MAX_ROUTE_MILES:
        raise PlanError(
            "too_long",
            f"Trips over {MAX_ROUTE_MILES:,} miles are not supported ({longest:,.0f} mi).",
        )
    paths = [p for p in paths if p.distance_mi <= MAX_ROUTE_MILES]

    # 2. Checkpoints + ETAs (optionally with Hours-of-Service stops, extra E5) -------------
    work = []
    for i, p in enumerate(paths):
        drive_s = route_duration_s(p, speed_cap)
        stops = hos_schedule(drive_s) if req.hos else []
        clock = make_drive_to_clock(stops) if stops else identity_clock
        work.append(
            _RouteWork(
                name=ROUTE_NAMES[i],
                path=p,
                checkpoints=place_checkpoints(p, req.interval_mi, req.departure, speed_cap, clock),
                duration_s=clock(drive_s),
                clock=clock,
                stops=stops,
            )
        )
    trip_end = req.departure + max(w.duration_s for w in work)
    if trip_end > now + FORECAST_HORIZON_S:
        raise PlanError(
            "beyond_forecast",
            "This trip ends beyond the 15-day forecast window. Choose an earlier departure.",
        )

    # 3. One weather fetch for checkpoints and the heatmap corridor --------------------------
    grid = build_corridor_grid([w.path.points for w in work])
    grid_nodes = {i: grid.node(i) for i in grid.fetch_indices}
    heat_end = req.departure + HEATMAP_HOURS * 3600
    window_start = req.departure - 3600
    # Extra E4 re-scores later departures from this same fetch, so cover the latest one too
    # (offsets whose trip would end past the forecast horizon are skipped).
    scan_offsets = [
        h for h in DEPARTURE_SCAN_OFFSETS_H if trip_end + h * 3600 <= now + FORECAST_HORIZON_S
    ]
    window_end = max(trip_end + scan_offsets[-1] * 3600, heat_end) + 3600
    points = [c.point for w in work for c in w.checkpoints] + list(grid_nodes.values())
    simulated = isinstance(weather, StormScenarioWeather)
    try:
        batch = weather.hourly(points, window_start, window_end)
    except UpstreamError:
        # Demo deployments must not fail on stage: fall back to the (clearly labelled) simulation.
        if not settings.TRIPS["DEMO_MODE"] or simulated:
            raise
        logger.warning("weather API failed in demo mode; using the simulated storm scenario")
        weather = StormScenarioWeather(req.origin, req.destination, req.departure)
        simulated = True
        batch = weather.hourly(points, window_start, window_end)

    # 4. Weather at ETA → risk → summaries -------------------------------------------------
    missing_checkpoints = 0
    for w in work:
        w.checkpoints, missing = _assess(w.checkpoints, batch, req.load_lb)
        missing_checkpoints += missing
        w.summary = summarize(w.checkpoints, w.path.distance_mi, w.duration_s)

    summaries = [w.summary for w in work if w.summary is not None]
    order = rank(summaries)
    reason = recommendation_reason(summaries, order, [w.name for w in work])
    rank_of = {route_idx: pos + 1 for pos, route_idx in enumerate(order)}

    # 5. Warnings ----------------------------------------------------------------------------
    warnings: list[str] = [SIMULATED_WARNING] if simulated else []
    if len(work) < 3:
        warnings.append(
            f"Only {len(work)} distinct route{'s' if len(work) > 1 else ''} could be found "
            "between these places."
        )
    if missing_checkpoints:
        warnings.append(
            f"No forecast was available for {missing_checkpoints} checkpoint(s); they are shown "
            "as 'no data' and excluded from the risk average."
        )
    if trip_end - now > LOW_CONFIDENCE_AFTER_S:
        warnings.append("Part of this trip is more than 3 days out; forecasts are less certain.")

    return {
        "request": {
            "origin": {**_ll(req.origin), "label": req.origin_label},
            "destination": {**_ll(req.destination), "label": req.destination_label},
            "departure_time": req.departure,
            "load_weight_lb": req.load_lb,
            "interval_miles": req.interval_mi,
            "simulate_storm": req.simulate_storm,
            "hos": req.hos,
        },
        "routes": [
            {
                **_route_json(i, w, rank_of[i], req.departure),
                "stops": _stops_json(w, req.departure, speed_cap),
                "why_not": None
                if i == order[0]
                else why_not_chosen(summaries[order[0]], summaries[i], work[order[0]].name),
            }
            for i, w in enumerate(work)
        ],
        "recommended_route_id": work[order[0]].name,
        "recommendation_reason": reason,
        "heatmap": _heatmap_json(grid, grid_nodes, batch, req),
        **_departure_scan(work, batch, req, speed_cap, scan_offsets),
        "warnings": warnings,
        "meta": {
            "truck_speed_cap_mph": speed_cap,
            "weather_source": "simulated" if simulated else "open-meteo",
            "routing_source": "recorded"
            if isinstance(routing, FixtureRouting) and routing.has(req.origin, req.destination)
            else "osrm",
            "demo_mode": bool(settings.TRIPS["DEMO_MODE"]),
            "weather_requests": batch.upstream_calls,
            "weather_locations_fetched": batch.locations_fetched,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "generated_at": now,
        },
    }


def _assess(
    checkpoints: list[Checkpoint], batch: WeatherBatch, load_lb: float
) -> tuple[list[Checkpoint], int]:
    """Attach the forecast at each checkpoint's ETA and its risk; returns (checkpoints, missing)."""
    out, missing = [], 0
    for c in checkpoints:
        series = batch.at(c.point)
        wx = weather_at(series, c.eta) if series is not None else None
        if wx is None:
            missing += 1
            out.append(c)
        else:
            out.append(dataclasses.replace(c, weather=wx, risk=classify(wx, load_lb)))
    return out, missing


def _departure_scan(
    work: list[_RouteWork],
    batch: WeatherBatch,
    req: PlanRequest,
    speed_cap: float,
    offsets: list[int],
) -> dict[str, Any]:
    """Extra E4: best route for each later departure, re-scored from the weather already fetched.

    Checkpoint *positions* don't depend on departure time, only their ETAs do, so every offset
    reuses the same forecast cells: no extra weather API calls. The best option is chosen with
    the same ``rank`` used for the route recommendation.
    """
    options: list[dict[str, Any]] = []
    best_summaries: list[RouteSummary] = []
    for h in offsets:
        dep = req.departure + h * 3600
        summaries = []
        for w in work:
            cps = place_checkpoints(w.path, req.interval_mi, dep, speed_cap, w.clock)
            cps, _ = _assess(cps, batch, req.load_lb)
            summaries.append(summarize(cps, w.path.distance_mi, w.duration_s))
        best_idx = rank(summaries)[0]
        s = summaries[best_idx]
        best_summaries.append(s)
        options.append(
            {
                "offset_h": h,
                "departure": dep,
                "route_id": work[best_idx].name,
                "miles_by_level": {
                    k.name.lower(): round(m, 1) for k, m in s.miles_by_level.items()
                },
                "avg_risk": round(s.avg_risk, 3),
                "duration_s": round(s.duration_s),
                "no_travel": s.no_travel,
                "best": False,
            }
        )
    if not options:
        return {"departure_options": [], "departure_advice": None}
    winner = rank(best_summaries)[0]  # ties keep the earliest departure (stable ranking)
    options[winner]["best"] = True
    if winner == 0:
        advice = (
            f"Leaving at your planned time is as safe as any start in the next {offsets[-1]} h."
        )
    else:
        c = deciding_criterion(best_summaries[winner], best_summaries[0])
        o = options[winner]
        advice = (
            f"Leaving {o['offset_h']} h later on {o['route_id']} gives the {c.label}: "
            f"{c.fmt(c.value(best_summaries[winner]))} vs {c.fmt(c.value(best_summaries[0]))} "
            "at your planned time."
            if c is not None
            else f"Leaving {o['offset_h']} h later is equally safe."
        )
    return {"departure_options": options, "departure_advice": advice}


# ------------------------------------------------------------------------------ serialisation
def _ll(p: LatLon) -> dict[str, float]:
    return {"lat": round(p.lat, 5), "lon": round(p.lon, 5)}


def _route_json(idx: int, w: _RouteWork, rank_pos: int, departure: float) -> dict[str, Any]:
    s = w.summary
    assert s is not None
    display = simplify(w.path.points, DISPLAY_SIMPLIFY_DEG)
    return {
        "id": w.name,
        "name": w.name,
        "via": w.path.label,
        "source": w.path.source,
        "rank": rank_pos,
        "recommended": rank_pos == 1,
        "geometry": [[round(p.lon, 5), round(p.lat, 5)] for p in display],  # GeoJSON order
        "summary": {
            "distance_mi": round(s.distance_mi, 1),
            "duration_s": round(s.duration_s),
            "departure": departure,
            "arrival": departure + s.duration_s,
            "miles_by_level": {
                lvl.name.lower(): round(m, 1) for lvl, m in s.miles_by_level.items()
            },
            "unknown_miles": round(s.unknown_miles, 1),
            "avg_risk": round(s.avg_risk, 3),
            "max_level": None if s.max_level is None else int(s.max_level),
            "no_travel": s.no_travel,
        },
        "checkpoints": [_checkpoint_json(c) for c in w.checkpoints],
    }


def _stops_json(w: _RouteWork, departure: float, speed_cap: float) -> list[dict[str, Any]]:
    """Extra E5: where and when each mandatory stop happens."""
    out = []
    for st in w.stops:
        dist, pt = point_at_drive_time(w.path, speed_cap, st.at_drive_s)
        start = departure + w.clock(st.at_drive_s)
        out.append(
            {
                "kind": st.kind,
                "label": st.label,
                "distance_mi": round(dist, 1),
                **_ll(pt),
                "start": round(start),
                "end": round(start + st.duration_s),
            }
        )
    return out


def _checkpoint_json(c: Checkpoint) -> dict[str, Any]:
    out: dict[str, Any] = {
        "index": c.index,
        "distance_mi": round(c.distance_mi, 1),
        **_ll(c.point),
        "eta": round(c.eta),
        "weather": None,
        "risk": None,
    }
    if c.weather is not None:
        out["weather"] = {
            "wind_mph": round(c.weather.wind_mph, 1),
            "gust_mph": None if c.weather.gust_mph is None else round(c.weather.gust_mph, 1),
            "rain_in_hr": round(c.weather.rain_in_hr, 3),
            "snow_in_hr": round(c.weather.snow_in_hr, 3),
            "valid_time": c.weather.valid_time,
        }
    if c.risk is not None:
        out["risk"] = {
            "level": int(c.risk.level),
            "label": c.risk.level.label,
            "wind_level": int(c.risk.wind_level),
            "rain_level": int(c.risk.rain_level),
            "snow_level": int(c.risk.snow_level),
            "load_rule": c.risk.load_rule,
            "reasons": list(c.risk.reasons),
        }
    return out


def _heatmap_json(grid, nodes: dict[int, LatLon], batch: WeatherBatch, req: PlanRequest) -> dict:
    """Hourly frames for hours 0..48 after departure, one value per fetched grid node.

    ``level`` is the overall risk level under the same rules (incl. load) as the checkpoints,
    -1 where no forecast is available.
    """
    node_ids = list(nodes)
    series = [batch.at(nodes[i]) for i in node_ids]
    level: list[list[int]] = []
    wind: list[list[float | None]] = []
    rain: list[list[float | None]] = []
    snow: list[list[float | None]] = []
    for h in range(HEATMAP_HOURS + 1):
        t = req.departure + h * 3600
        lv, wd, rn, sn = [], [], [], []
        for s in series:
            wx = weather_at(s, t) if s is not None else None
            if wx is None:
                lv.append(-1)
                wd.append(None)
                rn.append(None)
                sn.append(None)
                continue
            lv.append(classify_values(wx.wind_mph, wx.rain_in_hr, wx.snow_in_hr, req.load_lb))
            wd.append(round(wx.wind_mph, 1))
            rn.append(round(wx.rain_in_hr, 3))
            sn.append(round(wx.snow_in_hr, 3))
        level.append(lv)
        wind.append(wd)
        rain.append(rn)
        snow.append(sn)
    return {
        "grid": {
            "lat0": grid.lat0,
            "lon0": grid.lon0,
            "dlat": grid.dlat,
            "dlon": grid.dlon,
            "n_lat": grid.n_lat,
            "n_lon": grid.n_lon,
        },
        "core": [1 if c else 0 for c in grid.core],
        "nodes": node_ids,
        "start_time": req.departure,
        "step_s": 3600,
        "hours": HEATMAP_HOURS + 1,
        "levels": [lvl.label for lvl in RiskLevel],
        "level": level,
        "wind_mph": wind,
        "rain_in_hr": rain,
        "snow_in_hr": snow,
    }
