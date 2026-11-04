"""Place weather checkpoints along a route and work out when the truck reaches each one.

Pipeline per route:

1. ``truck_segment_durations``: routing APIs give car travel times, so each segment is slowed to at
   most ``speed_cap_mph`` (UNDERSTANDING A-12).
2. ``place_checkpoints``: checkpoints at 0, d, 2d, … miles along the route plus the destination.
   Each checkpoint's driving time is interpolated within the polyline segment that contains it, so
   ETA accuracy does not depend on the polyline's vertex density.
3. ``drive_to_clock`` maps cumulative *driving* seconds to elapsed *clock* seconds. The default is
   the identity; the Hours-of-Service extension (extra E5) plugs in a function that inserts
   mandatory breaks.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence

from .geo import cumulative_distances_mi, haversine_mi, lerp
from .types import Checkpoint, LatLon, RoutePath

ALLOWED_INTERVALS_MI = (10, 25, 50)
# If the destination is closer than this to the last regular checkpoint, the regular checkpoint is
# dropped instead of keeping two nearly identical samples.
MIN_FINAL_GAP_MI = 0.5

DriveToClock = Callable[[float], float]


def identity_clock(driving_s: float) -> float:
    return driving_s


def truck_segment_durations(
    points: Sequence[LatLon], seg_durations_s: Sequence[float], speed_cap_mph: float
) -> list[float]:
    """Per-segment durations, never faster than ``speed_cap_mph``."""
    if len(seg_durations_s) != len(points) - 1:
        raise ValueError("seg_durations_s must have exactly len(points) - 1 entries")
    if speed_cap_mph <= 0:
        raise ValueError("speed_cap_mph must be positive")
    out = []
    for i, dur in enumerate(seg_durations_s):
        min_dur = haversine_mi(points[i], points[i + 1]) / speed_cap_mph * 3600
        out.append(max(float(dur), min_dur))
    return out


def cumulative(values: Sequence[float]) -> list[float]:
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


def checkpoint_distances(total_mi: float, interval_mi: float) -> list[float]:
    """0, d, 2d, … < total, then total (with the near-duplicate rule above)."""
    if interval_mi <= 0:
        raise ValueError("interval_mi must be positive")
    if total_mi <= 0:
        return [0.0]
    dists: list[float] = []
    k = 0
    while k * interval_mi < total_mi:
        dists.append(k * interval_mi)
        k += 1
    if len(dists) > 1 and total_mi - dists[-1] < MIN_FINAL_GAP_MI:
        dists.pop()
    dists.append(total_mi)
    return dists


def place_checkpoints(
    route: RoutePath,
    interval_mi: float,
    departure: float,
    speed_cap_mph: float,
    drive_to_clock: DriveToClock = identity_clock,
) -> list[Checkpoint]:
    """Checkpoints with positions and ETAs (no weather yet)."""
    pts = route.points
    if len(pts) < 2:
        raise ValueError("A route needs at least two points")
    cum_d = cumulative_distances_mi(pts)
    cum_t = cumulative(truck_segment_durations(pts, route.seg_durations_s, speed_cap_mph))
    total = cum_d[-1]

    checkpoints = []
    for idx, target in enumerate(checkpoint_distances(total, interval_mi)):
        # Segment i such that cum_d[i] <= target <= cum_d[i + 1].
        i = min(max(bisect_right(cum_d, target) - 1, 0), len(pts) - 2)
        seg = cum_d[i + 1] - cum_d[i]
        f = 0.0 if seg == 0 else min(1.0, max(0.0, (target - cum_d[i]) / seg))
        drive_s = cum_t[i] + (cum_t[i + 1] - cum_t[i]) * f
        checkpoints.append(
            Checkpoint(
                index=idx,
                distance_mi=target,
                point=lerp(pts[i], pts[i + 1], f),
                eta=departure + drive_to_clock(drive_s),
            )
        )
    return checkpoints


def route_duration_s(
    route: RoutePath, speed_cap_mph: float, drive_to_clock: DriveToClock = identity_clock
) -> float:
    """Total trip clock time with the truck speed cap (and breaks, if a clock function is given)."""
    drive = sum(truck_segment_durations(route.points, route.seg_durations_s, speed_cap_mph))
    return drive_to_clock(drive)


def position_at_time(checkpoints: Sequence[Checkpoint], t: float) -> LatLon | None:
    """Truck position at epoch ``t``, interpolated between checkpoints; None outside the trip."""
    if not checkpoints or t < checkpoints[0].eta or t > checkpoints[-1].eta:
        return None
    etas = [c.eta for c in checkpoints]
    i = min(max(bisect_right(etas, t) - 1, 0), len(checkpoints) - 2) if len(etas) > 1 else 0
    if len(checkpoints) == 1:
        return checkpoints[0].point
    a, b = checkpoints[i], checkpoints[i + 1]
    span = b.eta - a.eta
    return lerp(a.point, b.point, 0.0 if span <= 0 else (t - a.eta) / span)


def point_at_drive_time(
    route: RoutePath, speed_cap_mph: float, drive_s: float
) -> tuple[float, LatLon]:
    """(distance along the route, position) after ``drive_s`` seconds of truck driving."""
    pts = route.points
    cum_d = cumulative_distances_mi(pts)
    cum_t = cumulative(truck_segment_durations(pts, route.seg_durations_s, speed_cap_mph))
    t = min(max(drive_s, 0.0), cum_t[-1])
    i = min(max(bisect_right(cum_t, t) - 1, 0), len(pts) - 2)
    span = cum_t[i + 1] - cum_t[i]
    f = 0.0 if span == 0 else (t - cum_t[i]) / span
    return cum_d[i] + (cum_d[i + 1] - cum_d[i]) * f, lerp(pts[i], pts[i + 1], f)
