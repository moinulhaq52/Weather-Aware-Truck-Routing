"""Spherical geometry helpers (pure Python, no GIS dependencies).

Accuracy notes: haversine on a sphere of radius 3958.8 mi is within ~0.5% of the WGS84 ellipsoid,
which is far below routing/forecast uncertainty. Linear lat/lon interpolation is only used
*within* a single polyline segment (typically < 1 mi long), where it matches a great-circle.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .types import LatLon

EARTH_RADIUS_MI = 3958.8
METERS_PER_MILE = 1609.344


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distances_mi(points: Sequence[LatLon]) -> list[float]:
    """``out[i]`` = distance from ``points[0]`` to ``points[i]`` along the polyline."""
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine_mi(points[i - 1], points[i]))
    return out


def lerp(a: LatLon, b: LatLon, f: float) -> LatLon:
    return LatLon(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f)


def bearing_deg(a: LatLon, b: LatLon) -> float:
    """Initial great-circle bearing from a to b, degrees clockwise from north."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlon = math.radians(b.lon - a.lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination(origin: LatLon, bearing: float, distance_mi: float) -> LatLon:
    """Point reached by travelling ``distance_mi`` from ``origin`` on initial ``bearing``."""
    d = distance_mi / EARTH_RADIUS_MI
    br = math.radians(bearing)
    lat1, lon1 = math.radians(origin.lat), math.radians(origin.lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return LatLon(math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def midpoint(a: LatLon, b: LatLon) -> LatLon:
    return destination(a, bearing_deg(a, b), haversine_mi(a, b) / 2)


def offset_midpoint(a: LatLon, b: LatLon, fraction: float, side: int) -> LatLon:
    """Midpoint of a–b pushed sideways by ``fraction`` × |ab|; ``side`` +1 = right, −1 = left.

    Used to synthesise alternative routes through a via-point when the routing API returns fewer
    than three options.
    """
    mid = midpoint(a, b)
    heading = bearing_deg(mid, b)
    return destination(mid, heading + 90 * side, haversine_mi(a, b) * fraction)


def simplify(points: Sequence[LatLon], tolerance_deg: float) -> list[LatLon]:
    """Douglas–Peucker simplification (iterative, so long routes can't overflow the stack).

    Works in planar degrees, which is fine for *display* geometry. Never use the result for
    distance or ETA maths.
    """
    return [points[i] for i in simplify_indices(points, tolerance_deg)]


def simplify_indices(points: Sequence[LatLon], tolerance_deg: float) -> list[int]:
    """Indices of the vertices Douglas–Peucker keeps (always includes the first and last)."""
    n = len(points)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_deg * tolerance_deg
    while stack:
        start, end = stack.pop()
        a, b = points[start], points[end]
        dx, dy = b.lon - a.lon, b.lat - a.lat
        seg2 = dx * dx + dy * dy
        best_i, best_d2 = -1, tol2
        for i in range(start + 1, end):
            p = points[i]
            if seg2 == 0:
                d2 = (p.lon - a.lon) ** 2 + (p.lat - a.lat) ** 2
            else:
                t = max(0.0, min(1.0, ((p.lon - a.lon) * dx + (p.lat - a.lat) * dy) / seg2))
                ex, ey = a.lon + t * dx - p.lon, a.lat + t * dy - p.lat
                d2 = ex * ex + ey * ey
            if d2 > best_d2:
                best_i, best_d2 = i, d2
        if best_i != -1:
            keep[best_i] = True
            stack.append((start, best_i))
            stack.append((best_i, end))
    return [i for i, k in enumerate(keep) if k]


def resample(points: Sequence[LatLon], spacing_mi: float) -> list[LatLon]:
    """Points every ``spacing_mi`` along the polyline (plus the final point)."""
    if not points:
        return []
    cum = cumulative_distances_mi(points)
    total = cum[-1]
    out: list[LatLon] = []
    target, i = 0.0, 0
    # The epsilon stops float noise from adding a near-duplicate point right before the end.
    while target < total - 1e-6:
        while i < len(cum) - 2 and cum[i + 1] < target:
            i += 1
        seg = cum[i + 1] - cum[i]
        f = 0.0 if seg == 0 else (target - cum[i]) / seg
        out.append(lerp(points[i], points[i + 1], f))
        target += spacing_mi
    out.append(points[-1])
    return out


def bbox(points: Sequence[LatLon]) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon)."""
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    return min(lats), min(lons), max(lats), max(lons)


class SpatialIndex:
    """Grid hash of sampled route points for fast 'is this point near the route' queries."""

    def __init__(self, points: Sequence[LatLon], radius_mi: float):
        self.radius = radius_mi
        self.cell = radius_mi / 69.0  # degrees of latitude per radius
        self.grid: dict[tuple[int, int], list[LatLon]] = {}
        for p in points:
            self.add(p)

    def add(self, p: LatLon) -> None:
        self.grid.setdefault(self._key(p), []).append(p)

    def _key(self, p: LatLon) -> tuple[int, int]:
        return (math.floor(p.lat / self.cell), math.floor(p.lon / self.cell))

    def near(self, p: LatLon) -> bool:
        ky, kx = self._key(p)
        # Longitude cells shrink with latitude; widen the search accordingly.
        span = max(1, math.ceil(1 / max(math.cos(math.radians(p.lat)), 0.1)))
        for dy in (-1, 0, 1):
            for dx in range(-span, span + 1):
                for q in self.grid.get((ky + dy, kx + dx), ()):
                    if haversine_mi(p, q) <= self.radius:
                        return True
        return False
