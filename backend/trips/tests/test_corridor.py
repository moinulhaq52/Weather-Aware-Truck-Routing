import time

import pytest

from trips.domain.corridor import build_corridor_grid
from trips.domain.geo import haversine_mi
from trips.domain.types import LatLon

from .helpers import straight_route


@pytest.mark.parametrize("miles", [30, 300, 1500, 2800])
def test_fetch_points_capped_for_any_trip_length(miles):
    r = straight_route(miles, n_points=400)
    grid = build_corridor_grid([r.points], max_points=220)
    assert 0 < sum(grid.fetch) <= 220
    assert sum(grid.core) <= sum(grid.fetch)


def test_every_route_point_is_inside_the_core_corridor():
    r = straight_route(600, n_points=200)
    grid = build_corridor_grid([r.points], buffer_mi=40)
    for p in r.points[::10]:
        row = round((p.lat - grid.lat0) / grid.dlat)
        col = round((p.lon - grid.lon0) / grid.dlon)
        assert grid.core[row * grid.n_lon + col]


def test_core_nodes_are_within_buffer_of_route():
    r = straight_route(300, n_points=100)
    grid = build_corridor_grid([r.points], buffer_mi=40)
    for i, inside in enumerate(grid.core):
        if inside:
            node = grid.node(i)
            nearest = min(haversine_mi(node, p) for p in r.points)
            assert nearest <= 40 + 5  # +5 mi for route resampling tolerance


def test_fetch_mask_adds_a_border_around_core():
    r = straight_route(200)
    grid = build_corridor_grid([r.points])
    border = [i for i in range(len(grid.core)) if grid.fetch[i] and not grid.core[i]]
    assert border  # the border exists, so interpolation at the corridor edge has neighbours


def test_grid_covers_multiple_routes():
    a = straight_route(300, lon=-100)
    b = straight_route(300, lon=-96)  # ~230 mi east
    grid = build_corridor_grid([a.points, b.points], buffer_mi=30)
    for route in (a, b):
        p = route.points[50]
        row = round((p.lat - grid.lat0) / grid.dlat)
        col = round((p.lon - grid.lon0) / grid.dlon)
        assert grid.core[row * grid.n_lon + col]
    # A point midway between the two routes (~115 mi from each) is outside the corridor.
    mid = LatLon(a.points[50].lat, -98)
    row = round((mid.lat - grid.lat0) / grid.dlat)
    col = round((mid.lon - grid.lon0) / grid.dlon)
    assert not grid.core[row * grid.n_lon + col]


def test_grid_is_fast_for_long_trips():
    r = straight_route(2800, n_points=5000)
    t = time.perf_counter()
    build_corridor_grid([r.points, r.points, r.points])
    assert time.perf_counter() - t < 1.5


def test_empty_routes_rejected():
    with pytest.raises(ValueError):
        build_corridor_grid([[]])
