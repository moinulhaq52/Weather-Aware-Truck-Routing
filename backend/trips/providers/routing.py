"""Routing provider: three distinct route options between two points.

The default provider is the public OSRM server (no API key). It returns at most two routes even
when asked for three (verified, RESEARCH §1.1), so missing options are synthesised by routing
through a via-point pushed sideways from the trip midpoint, then filtered so that every option is
genuinely different, not absurdly long, and free of out-and-back spurs.

The ``RoutingProvider`` protocol keeps the planner independent of OSRM, so a truck-aware keyed
provider (TomTom / HERE) can be swapped in.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from django.conf import settings
from django.core.cache import cache

from ..domain.geo import (
    METERS_PER_MILE,
    SpatialIndex,
    cumulative_distances_mi,
    haversine_mi,
    offset_midpoint,
    resample,
)
from ..domain.types import LatLon, RoutePath
from .http import UpstreamError, request_json

logger = logging.getLogger(__name__)

TARGET_ROUTES = 3
# Via-point offsets as a fraction of the straight-line distance, tried in order (both sides each).
# 0.06 is last: it often duplicates a native route, but rescues trips with few parallel highways.
VIA_OFFSETS = (0.12, 0.25, 0.06)
MAX_DURATION_RATIO = 1.6  # alternatives slower than 1.6x the fastest are not useful options
MAX_OVERLAP = 0.85  # alternatives sharing more than 85% of their length with another are duplicates
OVERLAP_RADIUS_MI = 0.6
SPUR_RADIUS_MI = 0.6  # must exceed half the 1 mi sampling step, or offset samples miss
MAX_SPUR_FRACTION = 0.04  # reject routes that double back on themselves (via-point detours)
ROUTE_CACHE_TTL_S = 6 * 3600
OSRM_MIN_INTERVAL_S = 0.5


class NoRouteError(Exception):
    """The provider answered, but there is no drivable route between the points."""


class RoutingProvider(Protocol):
    def routes(self, origin: LatLon, destination: LatLon) -> list[RoutePath]: ...


# --------------------------------------------------------------------------- OSRM
class OsrmProvider:
    service = "routing"

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.TRIPS["OSRM_BASE_URL"]).rstrip("/")

    def routes(self, origin: LatLon, destination: LatLon) -> list[RoutePath]:
        key = _cache_key("routes", origin, destination)
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = self._compute(origin, destination)
        cache.set(key, result, ROUTE_CACHE_TTL_S)
        return result

    def _compute(self, origin: LatLon, destination: LatLon) -> list[RoutePath]:
        native = self._request([origin, destination], alternatives=True)
        chosen = select_distinct(native, [])
        if len(chosen) < TARGET_ROUTES:
            for fraction in VIA_OFFSETS:
                vias = [offset_midpoint(origin, destination, fraction, side) for side in (1, -1)]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(
                        pool.map(lambda v: self._via_route(origin, v, destination), vias)
                    )
                candidates = [r for r in results if r is not None]
                chosen = select_distinct(candidates, chosen)
                if len(chosen) >= TARGET_ROUTES:
                    break
        return chosen[:TARGET_ROUTES]

    def _via_route(self, origin: LatLon, via: LatLon, destination: LatLon) -> RoutePath | None:
        try:
            routes = self._request([origin, via, destination], alternatives=False)
        except (UpstreamError, NoRouteError) as exc:
            # A failed *extra* option is not fatal: we still have the native routes.
            logger.info("via-point route skipped: %s", exc)
            return None
        if not routes:
            return None
        r = routes[0]
        return RoutePath(r.points, r.seg_durations_s, r.distance_mi, r.duration_s, r.label, "via")

    def _request(self, waypoints: Sequence[LatLon], alternatives: bool) -> list[RoutePath]:
        coords = ";".join(f"{p.lon:.6f},{p.lat:.6f}" for p in waypoints)
        params = {
            "alternatives": "3" if alternatives else "false",
            "overview": "full",
            "geometries": "geojson",
            "annotations": "duration,distance",
            "steps": "true",  # needed for leg summaries (road names used as route labels)
            "continue_straight": "true",  # no U-turns at via-points
        }
        try:
            body = request_json(
                "GET",
                f"{self.base_url}/route/v1/driving/{coords}",
                service=self.service,
                params=params,
                min_interval=OSRM_MIN_INTERVAL_S,
            )
        except UpstreamError as exc:
            # OSRM answers 400 with code NoRoute / NoSegment when the points can't be connected.
            if exc.status == 400:
                raise NoRouteError(str(exc)) from exc
            raise
        return parse_osrm(body)


def parse_osrm(body: dict[str, Any]) -> list[RoutePath]:
    """Convert an OSRM /route response into ``RoutePath`` objects."""
    code = body.get("code")
    if code in ("NoRoute", "NoSegment"):
        raise NoRouteError(body.get("message") or code)
    if code != "Ok":
        raise UpstreamError("routing", f"unexpected OSRM code {code!r}")
    out = []
    for r in body.get("routes", []):
        coords = r["geometry"]["coordinates"]
        points = tuple(LatLon(float(c[1]), float(c[0])) for c in coords)  # GeoJSON is [lon, lat]
        if len(points) < 2:
            continue
        durations: list[float] = []
        for leg in r.get("legs", []):
            durations.extend(float(x) for x in leg.get("annotation", {}).get("duration", []))
        total_s = float(r["duration"])
        durations = _reconcile_durations(points, durations, total_s)
        names = [leg.get("summary", "") for leg in r.get("legs", []) if leg.get("summary")]
        out.append(
            RoutePath(
                points=points,
                seg_durations_s=tuple(durations),
                distance_mi=float(r["distance"]) / METERS_PER_MILE,
                duration_s=total_s,
                label=_label_from_summaries(names),
            )
        )
    return out


def _reconcile_durations(
    points: Sequence[LatLon], durations: list[float], total_s: float
) -> list[float]:
    """Make per-segment durations consistent with the geometry and the route's total time.

    OSRM's annotation sum is slightly lower than ``route.duration`` (turn penalties are not in the
    annotations), so durations are scaled to the total. If counts don't match the geometry, fall
    back to distributing the total proportionally to segment length.
    """
    n = len(points) - 1
    if len(durations) == n and sum(durations) > 0:
        scale = total_s / sum(durations)
        return [d * scale for d in durations]
    seg = [haversine_mi(points[i], points[i + 1]) for i in range(n)]
    length = sum(seg) or 1.0
    return [total_s * s / length for s in seg]


def _label_from_summaries(names: Sequence[str]) -> str:
    """'US Highway 287, I 25' -> 'US Highway 287, I 25' (deduplicated across legs)."""
    parts: list[str] = []
    for name in names:
        for part in name.split(","):
            p = part.strip()
            if p and p not in parts:
                parts.append(p)
    return ", ".join(parts[:3])


# --------------------------------------------------------------------------- diversity filtering
def overlap_fraction(a: RoutePath, b: RoutePath, step_mi: float = 2.0) -> float:
    """Share of route ``a``'s length that runs along route ``b``."""
    samples = resample(a.points, step_mi)
    index = SpatialIndex(resample(b.points, step_mi / 4), OVERLAP_RADIUS_MI)
    return sum(index.near(p) for p in samples) / max(len(samples), 1)


def spur_fraction(route: RoutePath, step_mi: float = 1.0) -> float:
    """Share of the route that revisits road it drove >= 5 mi earlier (out-and-back spurs).

    Via-points that snap to a side road make OSRM drive there and back; such routes are artefacts,
    not real options.
    """
    samples = resample(route.points, step_mi)
    lag = max(1, round(5 / step_mi))
    index = SpatialIndex([], SPUR_RADIUS_MI)
    hits = 0
    for i in range(lag, len(samples)):
        index.add(samples[i - lag])
        if index.near(samples[i]):
            hits += 1
    return hits / max(len(samples), 1)


def select_distinct(
    candidates: Sequence[RoutePath], chosen: Sequence[RoutePath]
) -> list[RoutePath]:
    """Add candidates (in order) that are distinct, reasonably fast, and spur-free."""
    result = list(chosen)
    for cand in candidates:
        if len(result) >= TARGET_ROUTES:
            break
        fastest = min([r.duration_s for r in result] + [cand.duration_s])
        if result and cand.duration_s > MAX_DURATION_RATIO * fastest:
            continue
        if cand.source == "via" and spur_fraction(cand) > MAX_SPUR_FRACTION:
            continue
        if any(
            max(overlap_fraction(cand, r), overlap_fraction(r, cand)) > MAX_OVERLAP for r in result
        ):
            continue
        result.append(cand)
    return result


def _cache_key(prefix: str, *points: LatLon) -> str:
    raw = "|".join(f"{p.lat:.4f},{p.lon:.4f}" for p in points)
    return f"{prefix}:{hashlib.sha1(raw.encode()).hexdigest()}"


def route_length_mi(route: RoutePath) -> float:
    return cumulative_distances_mi(route.points)[-1]
