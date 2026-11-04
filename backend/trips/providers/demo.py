"""Extra E3: demo & resilience providers.

- ``StormScenarioWeather``: a deterministic, clearly-labelled **synthetic** storm laid across the
  trip corridor. It replaces only the forecast source; checkpoints, ETAs, risk rules, load rules,
  ranking and heatmap all run through the real code paths. It exists so the app can be
  demonstrated on calm-weather days, and as a fallback when the weather API is down in demo
  mode. Every response that uses it says so (``meta.weather_source == "simulated"`` + a warning).
- ``FixtureRouting``: replays real OSRM routes recorded by ``scripts/record_fixtures.py`` for the
  example trips, so a demo deployment doesn't depend on the public OSRM server. Other trips fall
  through to the live provider.
"""

from __future__ import annotations

import gzip
import json
import math
from functools import cache
from pathlib import Path

from ..domain.forecast import HourlySeries
from ..domain.geo import bearing_deg, destination, haversine_mi, midpoint
from ..domain.types import LatLon, RoutePath
from .routing import RoutingProvider
from .weather import WeatherBatch, cell_center, cell_of

FIXTURE_FILE = Path(__file__).resolve().parent.parent / "fixtures" / "routes.json.gz"
HOUR = 3600


# --------------------------------------------------------------------------- simulated storm
class StormScenarioWeather:
    """A storm whose core sits beside the direct line between origin and destination.

    Geometry (D = straight-line trip distance):
    - core starts at the trip midpoint pushed ``0.12·D`` to the right of the direct line and
      drifts along the trip bearing at 12 mph, so routes on that side meet it and others don't;
    - radius R = max(45, 0.13·D) mi; Gaussian fall-off from the core;
    - intensity ramps up over 4 h, peaks from hour 4 to 22, then decays (gone by ~hour 34);
    - at the core: 52 mph wind (Severe; No Travel for loads > 30,000 lb), 0.75 in/hr rain, or
      snow 2.6 in/hr where the core is north of 41°N; light background wind elsewhere.
    """

    def __init__(self, origin: LatLon, destination_: LatLon, departure: float):
        self.departure = departure
        d = haversine_mi(origin, destination_)
        self.heading = bearing_deg(origin, destination_)
        mid = midpoint(origin, destination_)
        self.start = destination(mid, self.heading + 90, 0.12 * d)
        self.radius = max(45.0, 0.13 * d)

    def center(self, t: float) -> LatLon:
        hours = (t - self.departure) / HOUR
        return destination(self.start, self.heading, 12.0 * hours)

    def intensity(self, t: float) -> float:
        h = (t - self.departure) / HOUR
        if h < 0:
            return 0.25
        if h < 4:
            return 0.25 + 0.75 * h / 4
        if h <= 22:
            return 1.0
        return max(0.0, 1.0 - (h - 22) / 12)

    def conditions(self, p: LatLon, t: float) -> tuple[float, float, float, float]:
        """(wind_mph, gust_mph, rain_in_hr, snow_in_hr) at ``p`` and epoch ``t``."""
        c = self.center(t)
        r = haversine_mi(p, c) / self.radius
        f = math.exp(-(r**2)) * self.intensity(t)
        # Deterministic gentle background variation so calm areas aren't perfectly flat.
        background = 7 + 3 * math.sin(p.lat * 1.7 + p.lon * 1.3 + t / 21_600)
        wind = background + 45 * f
        cold = c.lat > 41
        precip = 0.75 * f**1.6
        rain = 0.0 if cold else precip
        snow = 2.6 * f**1.6 if cold else 0.0
        return wind, wind * 1.35, rain, snow

    def hourly(self, points, start: float, end: float) -> WeatherBatch:
        t0 = int(start // HOUR * HOUR)
        times = tuple(range(t0, int(end) + 2 * HOUR, HOUR))
        batch = WeatherBatch()
        for cell in {cell_of(p) for p in points}:
            centre = cell_center(cell)
            rows = [self.conditions(centre, t) for t in times]
            batch.series[cell] = HourlySeries(
                times=times,
                wind_mph=tuple(round(x[0], 1) for x in rows),
                gust_mph=tuple(round(x[1], 1) for x in rows),
                rain_in_hr=tuple(round(x[2], 3) for x in rows),
                snow_in_hr=tuple(round(x[3], 3) for x in rows),
            )
        return batch


# --------------------------------------------------------------------------- recorded routes
def fixture_key(origin: LatLon, destination_: LatLon) -> str:
    return f"{origin.lat:.2f},{origin.lon:.2f}->{destination_.lat:.2f},{destination_.lon:.2f}"


@cache
def _load_fixtures() -> dict[str, list[dict]]:
    if not FIXTURE_FILE.exists():
        return {}
    with gzip.open(FIXTURE_FILE, "rt", encoding="utf-8") as f:
        return json.load(f)


def decode_route(d: dict) -> RoutePath:
    pts = tuple(LatLon(lat, lon) for lat, lon in d["points"])
    return RoutePath(
        points=pts,
        seg_durations_s=tuple(d["seg_durations_s"]),
        distance_mi=d["distance_mi"],
        duration_s=d["duration_s"],
        label=d["label"],
        source=d["source"],
    )


class FixtureRouting:
    """Recorded routes for known trips; everything else goes to ``fallback``."""

    def __init__(self, fallback: RoutingProvider):
        self.fallback = fallback

    def has(self, origin: LatLon, destination_: LatLon) -> bool:
        return fixture_key(origin, destination_) in _load_fixtures()

    def routes(self, origin: LatLon, destination_: LatLon) -> list[RoutePath]:
        recorded = _load_fixtures().get(fixture_key(origin, destination_))
        if recorded:
            return [decode_route(r) for r in recorded]
        return self.fallback.routes(origin, destination_)
