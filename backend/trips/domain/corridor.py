"""The heatmap grid: a regular lat/lon lattice covering the trip corridor.

The corridor is every place within ``buffer_mi`` of any route. Grid spacing adapts to the trip so
the number of forecast points stays under ``max_points`` (the free weather API counts each point
as one call, RESEARCH §1.2): about 0.15° for a short trip, up to ~0.6° for a cross-country one.
The frontend interpolates between nodes, so a coarse grid still renders as a smooth field.

Two masks are produced, both flat row-major arrays (index = row * n_lon + col):

- ``core``: nodes inside the corridor; the frontend fades the heatmap out beyond these.
- ``fetch``: ``core`` plus a one-node border, so interpolation at the corridor edge has neighbours.
  Forecasts are fetched for ``fetch`` nodes only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geo import SpatialIndex, bbox, resample
from .types import LatLon

MI_PER_DEG_LAT = 69.09
MIN_SPACING_DEG = 0.15  # finer than this adds API calls without adding forecast detail
MAX_SPACING_DEG = 1.5


@dataclass(frozen=True, slots=True)
class CorridorGrid:
    lat0: float  # latitude of row 0 (south edge)
    lon0: float  # longitude of column 0 (west edge)
    dlat: float
    dlon: float
    n_lat: int
    n_lon: int
    core: tuple[bool, ...]
    fetch: tuple[bool, ...]

    def node(self, idx: int) -> LatLon:
        r, c = divmod(idx, self.n_lon)
        return LatLon(round(self.lat0 + r * self.dlat, 5), round(self.lon0 + c * self.dlon, 5))

    @property
    def fetch_indices(self) -> list[int]:
        return [i for i, f in enumerate(self.fetch) if f]


def build_corridor_grid(
    routes: Sequence[Sequence[LatLon]], buffer_mi: float = 40.0, max_points: int = 220
) -> CorridorGrid:
    """Grid over all routes' corridor with at most ``max_points`` fetch nodes."""
    all_pts = [p for r in routes for p in r]
    if not all_pts:
        raise ValueError("At least one route point is required")
    min_lat, min_lon, max_lat, max_lon = bbox(all_pts)
    mid_lat = (min_lat + max_lat) / 2
    cos_lat = max(math.cos(math.radians(mid_lat)), 0.2)

    # First guess from corridor area ≈ total route length × corridor width.
    samples = [p for r in routes for p in resample(r, 5.0)]
    route_len = max(5.0 * len(samples), 1.0)
    area = route_len * 2 * buffer_mi
    spacing_mi = math.sqrt(area / max_points)
    dlat = min(max(spacing_mi / MI_PER_DEG_LAT, MIN_SPACING_DEG), MAX_SPACING_DEG)

    index = SpatialIndex(samples, buffer_mi)
    while True:
        grid = _grid(index, min_lat, min_lon, max_lat, max_lon, dlat, cos_lat, buffer_mi)
        if sum(grid.fetch) <= max_points or dlat >= MAX_SPACING_DEG:
            return grid
        dlat = min(dlat * 1.15, MAX_SPACING_DEG)


def _grid(
    index: SpatialIndex,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    dlat: float,
    cos_lat: float,
    buffer_mi: float,
) -> CorridorGrid:
    dlon = dlat / cos_lat  # roughly square cells in miles
    pad_lat = buffer_mi / MI_PER_DEG_LAT + dlat
    pad_lon = buffer_mi / (MI_PER_DEG_LAT * cos_lat) + dlon
    lat0 = math.floor((min_lat - pad_lat) / dlat) * dlat
    lon0 = math.floor((min_lon - pad_lon) / dlon) * dlon
    n_lat = math.ceil((max_lat + pad_lat - lat0) / dlat) + 1
    n_lon = math.ceil((max_lon + pad_lon - lon0) / dlon) + 1

    core = [False] * (n_lat * n_lon)
    for r in range(n_lat):
        for c in range(n_lon):
            if index.near(LatLon(lat0 + r * dlat, lon0 + c * dlon)):
                core[r * n_lon + c] = True

    fetch = list(core)
    for r in range(n_lat):
        for c in range(n_lon):
            if core[r * n_lon + c]:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < n_lat and 0 <= cc < n_lon:
                            fetch[rr * n_lon + cc] = True
    return CorridorGrid(lat0, lon0, dlat, dlon, n_lat, n_lon, tuple(core), tuple(fetch))
