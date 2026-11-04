"""Synthetic fixtures with known answers, shared across tests."""

import math

from trips.domain.geo import EARTH_RADIUS_MI
from trips.domain.types import LatLon, RoutePath

MI_PER_DEG_LAT = 2 * math.pi * EARTH_RADIUS_MI / 360  # ≈ 69.09 mi


def straight_route(
    miles: float,
    n_points: int = 101,
    speed_mph: float = 60.0,
    start_lat: float = 30.0,
    lon: float = -100.0,
    label: str = "",
) -> RoutePath:
    """A due-north route along a meridian, so distance is exactly proportional to latitude."""
    pts = tuple(
        LatLon(start_lat + (miles / MI_PER_DEG_LAT) * i / (n_points - 1), lon)
        for i in range(n_points)
    )
    seg_mi = miles / (n_points - 1)
    durs = tuple(seg_mi / speed_mph * 3600 for _ in range(n_points - 1))
    return RoutePath(
        points=pts,
        seg_durations_s=durs,
        distance_mi=miles,
        duration_s=sum(durs),
        label=label,
    )
