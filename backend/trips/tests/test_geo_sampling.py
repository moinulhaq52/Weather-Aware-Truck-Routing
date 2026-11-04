import itertools

import pytest

from trips.domain.forecast import HourlySeries, interval_row, nearest_row, weather_at
from trips.domain.geo import (
    bearing_deg,
    cumulative_distances_mi,
    destination,
    haversine_mi,
    offset_midpoint,
    resample,
    simplify,
)
from trips.domain.sampling import (
    checkpoint_distances,
    place_checkpoints,
    position_at_time,
    route_duration_s,
    truck_segment_durations,
)
from trips.domain.types import LatLon

from .helpers import straight_route

T0 = 1_800_000_000 - (1_800_000_000 % 3600)  # an exact hour, epoch seconds


# ---------------------------------------------------------------- geo
def test_haversine_known_distance():
    # Dallas -> Denver great-circle distance is about 663 miles.
    d = haversine_mi(LatLon(32.7767, -96.797), LatLon(39.7392, -104.9903))
    assert 655 < d < 670


def test_haversine_coordinate_order_matters():
    # Guard against lat/lon swaps: these two pairs are very different places.
    assert haversine_mi(LatLon(10, 50), LatLon(10, 51)) != pytest.approx(
        haversine_mi(LatLon(50, 10), LatLon(51, 10))
    )


def test_destination_roundtrip():
    a = LatLon(35.0, -90.0)
    b = destination(a, 45, 100)
    assert haversine_mi(a, b) == pytest.approx(100, rel=1e-6)
    assert bearing_deg(a, b) == pytest.approx(45, abs=0.01)


def test_offset_midpoint_is_on_requested_side():
    a, b = LatLon(30, -100), LatLon(40, -100)  # due north
    right = offset_midpoint(a, b, 0.15, side=1)
    left = offset_midpoint(a, b, 0.15, side=-1)
    assert right.lon > -100 > left.lon  # heading north, right is east
    assert haversine_mi(LatLon(35, -100), right) == pytest.approx(
        0.15 * haversine_mi(a, b), rel=0.02
    )


def test_simplify_keeps_endpoints_and_drops_collinear_points():
    r = straight_route(100, n_points=500)
    s = simplify(r.points, 1e-4)
    assert s[0] == r.points[0]
    assert s[-1] == r.points[-1]
    assert len(s) == 2


def test_simplify_keeps_corners():
    pts = [LatLon(0, 0), LatLon(0, 0.5), LatLon(0, 1), LatLon(0.5, 1), LatLon(1, 1)]
    assert LatLon(0, 1) in simplify(pts, 1e-3)


def test_resample_spacing():
    r = straight_route(100)
    pts = resample(r.points, 10)
    assert len(pts) == 11
    cum = cumulative_distances_mi(pts)
    assert cum[-1] == pytest.approx(100, rel=1e-3)


# ---------------------------------------------------------------- sampling
@pytest.mark.parametrize(
    ("total", "interval", "expected"),
    [
        (100, 25, [0, 25, 50, 75, 100]),
        (110, 25, [0, 25, 50, 75, 100, 110]),
        (100.3, 25, [0, 25, 50, 75, 100.3]),  # 100 is within 0.5 mi of the end -> merged
        (8, 10, [0, 8]),  # trip shorter than the interval still gets origin + destination
        (0, 10, [0]),
    ],
)
def test_checkpoint_distances(total, interval, expected):
    assert checkpoint_distances(total, interval) == pytest.approx(expected)


@pytest.mark.parametrize("interval", [10, 25, 50])
def test_checkpoints_every_interval_with_correct_etas(interval):
    r = straight_route(300, n_points=37, speed_mph=60)  # vertices don't line up with checkpoints
    cps = place_checkpoints(r, interval, departure=T0, speed_cap_mph=65)
    assert cps[0].distance_mi == 0 and cps[0].eta == T0
    assert cps[-1].distance_mi == pytest.approx(300, rel=1e-6)
    for cp in cps:
        # 60 mph, under the cap -> 1 minute per mile
        assert cp.eta - T0 == pytest.approx(cp.distance_mi * 60, abs=1)
    # positions match distances (meridian route: distance ∝ latitude)
    assert haversine_mi(r.points[0], cps[1].point) == pytest.approx(interval, rel=1e-3)
    assert all(b.eta >= a.eta for a, b in itertools.pairwise(cps))


def test_truck_speed_cap_slows_fast_segments():
    r = straight_route(100, speed_mph=80)
    durs = truck_segment_durations(r.points, r.seg_durations_s, speed_cap_mph=65)
    assert sum(durs) == pytest.approx(100 / 65 * 3600, rel=1e-3)
    # slower-than-cap segments are untouched
    slow = straight_route(100, speed_mph=40)
    assert sum(truck_segment_durations(slow.points, slow.seg_durations_s, 65)) == pytest.approx(
        slow.duration_s
    )
    assert route_duration_s(r, 65) == pytest.approx(100 / 65 * 3600, rel=1e-3)


def test_truck_segment_durations_validates_lengths():
    r = straight_route(10)
    with pytest.raises(ValueError):
        truck_segment_durations(r.points, r.seg_durations_s[:-1], 65)


def test_drive_to_clock_hook_shifts_etas():
    r = straight_route(100, speed_mph=60)
    cps = place_checkpoints(r, 50, T0, 65, drive_to_clock=lambda s: s * 2)
    assert cps[-1].eta - T0 == pytest.approx(2 * 100 * 60, abs=1)


def test_position_at_time():
    r = straight_route(100, speed_mph=60)
    cps = place_checkpoints(r, 10, T0, 65)
    mid = position_at_time(cps, T0 + 50 * 60)
    assert mid is not None
    assert haversine_mi(r.points[0], mid) == pytest.approx(50, rel=1e-3)
    assert position_at_time(cps, T0 - 1) is None
    assert position_at_time(cps, T0 + 101 * 60) is None


# ---------------------------------------------------------------- forecast hour selection
def series(n=6, start=T0):
    times = tuple(start + h * 3600 for h in range(n))
    return HourlySeries(
        times=times,
        wind_mph=tuple(float(h * 10) for h in range(n)),  # wind = 10 × hour index
        gust_mph=tuple(float(h * 10 + 5) for h in range(n)),
        rain_in_hr=tuple(h / 100 for h in range(n)),  # rain = hour index / 100
        snow_in_hr=tuple(0.0 for _ in range(n)),
    )


def test_precip_uses_preceding_hour_row():
    s = series()
    # ETA 01:20 -> precip from the 02:00 row (covers 01:00-02:00)
    assert interval_row(s.times, T0 + 3600 + 1200) == 2
    # ETA exactly 01:00 -> the 02:00 row (the hour about to be driven)
    assert interval_row(s.times, T0 + 3600) == 2
    # Past the series end -> None
    assert interval_row(s.times, T0 + 5 * 3600) is None


def test_wind_uses_nearest_row():
    s = series()
    assert nearest_row(s.times, T0 + 3600 + 1200) == 1  # 01:20 -> 01:00
    assert nearest_row(s.times, T0 + 3600 + 2400) == 2  # 01:40 -> 02:00
    assert nearest_row(s.times, T0 - 4000) is None


def test_weather_at_combines_rows():
    w = weather_at(series(), T0 + 3600 + 1200)
    assert w is not None
    assert w.wind_mph == 10  # nearest: hour 1
    assert w.rain_in_hr == pytest.approx(0.02)  # interval: hour 2
    assert w.valid_time == T0 + 2 * 3600


def test_weather_at_missing_values_returns_none():
    s = series()
    s = HourlySeries(s.times, s.wind_mph, s.gust_mph, (None,) * len(s), s.snow_in_hr)
    assert weather_at(s, T0 + 1800) is None


def test_weather_at_out_of_window_returns_none():
    assert weather_at(series(), T0 + 100 * 3600) is None
