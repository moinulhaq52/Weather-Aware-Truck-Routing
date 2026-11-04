import httpx
import pytest
import respx

from trips.domain.types import LatLon, RoutePath
from trips.providers import http as http_mod
from trips.providers.http import UpstreamError, request_json
from trips.providers.routing import (
    NoRouteError,
    OsrmProvider,
    overlap_fraction,
    parse_osrm,
    select_distinct,
    spur_fraction,
)

from .osrm_fakes import dogleg, line, ok, osrm_route

BASE = "https://osrm.test"
O, D = LatLon(32.78, -96.80), LatLon(39.74, -104.99)  # noqa: E741


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Retries/backoff must not slow the suite down."""
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)


def as_path(route_dict, source="native"):
    p = parse_osrm(ok(route_dict))[0]
    return RoutePath(p.points, p.seg_durations_s, p.distance_mi, p.duration_s, p.label, source)


# ------------------------------------------------------------------ parsing
def test_parse_converts_lonlat_and_reconciles_durations():
    body = ok(osrm_route(line(O, D), summary="US Highway 287, I 25"))
    (r,) = parse_osrm(body)
    assert r.points[0] == O  # [lon, lat] -> LatLon(lat, lon)
    assert len(r.seg_durations_s) == len(r.points) - 1
    assert sum(r.seg_durations_s) == pytest.approx(r.duration_s)  # scaled to route total
    assert r.label == "US Highway 287, I 25"


def test_parse_multi_leg_route_concatenates_annotations():
    body = ok(osrm_route(dogleg(O, LatLon(37, -99), D), legs=2, summary="I 35"))
    (r,) = parse_osrm(body)
    assert len(r.seg_durations_s) == len(r.points) - 1
    assert r.label == "I 35"  # duplicated leg summaries collapse


def test_parse_mismatched_annotations_falls_back_to_proportional():
    route = osrm_route(line(O, D))
    route["legs"][0]["annotation"]["duration"] = route["legs"][0]["annotation"]["duration"][:-3]
    (r,) = parse_osrm(ok(route))
    assert len(r.seg_durations_s) == len(r.points) - 1
    assert sum(r.seg_durations_s) == pytest.approx(r.duration_s)


def test_parse_no_route_code():
    with pytest.raises(NoRouteError):
        parse_osrm({"code": "NoRoute", "message": "Impossible route"})


def test_parse_unexpected_code():
    with pytest.raises(UpstreamError):
        parse_osrm({"code": "TooBig"})


# ------------------------------------------------------------------ diversity filters
def test_overlap_identical_and_disjoint():
    a = as_path(osrm_route(line(O, D)))
    far = as_path(osrm_route(line(LatLon(O.lat, O.lon + 3), LatLon(D.lat, D.lon + 3))))
    assert overlap_fraction(a, a) == pytest.approx(1.0)
    assert overlap_fraction(a, far) == 0


def test_spur_detected_for_out_and_back():
    there = line(O, LatLon(33.5, -96.8), 30)
    back = list(reversed(there))[1:]
    onward = line(O, D, 60)[1:]
    spur = as_path(osrm_route(there + back + onward), source="via")
    straight = as_path(osrm_route(line(O, D)), source="via")
    assert spur_fraction(spur) > 0.04
    assert spur_fraction(straight) == 0


def test_select_distinct_rejects_duplicates_and_slow_routes():
    fast = as_path(osrm_route(line(O, D), speed_mph=60))
    dup = as_path(osrm_route(line(O, D), speed_mph=59), source="via")
    slow = as_path(
        osrm_route(dogleg(O, LatLon(36, -94), D), speed_mph=20), source="via"
    )  # > 1.6x slower
    different = as_path(osrm_route(dogleg(O, LatLon(37.5, -99.5), D), speed_mph=60), source="via")
    chosen = select_distinct([fast, dup, slow, different], [])
    assert chosen == [fast, different]


# ------------------------------------------------------------------ provider (HTTP mocked)
@respx.mock
def test_provider_synthesises_third_route_with_via_points():
    native = ok(
        osrm_route(line(O, D), summary="I 25"),
        osrm_route(dogleg(O, LatLon(37.5, -99.0), D), speed_mph=58, summary="US 287"),
    )
    via = ok(osrm_route(dogleg(O, LatLon(35.0, -103.0), D), speed_mph=57, legs=2, summary="I 40"))

    def handler(request):
        coords = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=native if coords.count(";") == 1 else via)

    respx.get(url__startswith=f"{BASE}/route/v1/driving/").mock(side_effect=handler)
    routes = OsrmProvider(BASE).routes(O, D)
    assert len(routes) == 3
    assert [r.source for r in routes] == ["native", "native", "via"]
    assert routes[2].label == "I 40"


@respx.mock
def test_provider_caches_routes():
    route = respx.get(url__startswith=f"{BASE}/route/v1/driving/").mock(
        return_value=httpx.Response(200, json=ok(osrm_route(line(O, D))))
    )
    p = OsrmProvider(BASE)
    p.routes(O, D)
    calls = route.call_count
    p.routes(O, D)
    assert route.call_count == calls  # second call served from cache


@respx.mock
def test_provider_no_route_maps_400_to_no_route_error():
    respx.get(url__startswith=f"{BASE}/route/v1/driving/").mock(
        return_value=httpx.Response(400, json={"code": "NoRoute", "message": "Impossible route"})
    )
    with pytest.raises(NoRouteError):
        OsrmProvider(BASE).routes(O, D)


@respx.mock
def test_failed_via_route_is_not_fatal():
    native = ok(osrm_route(line(O, D)))

    def handler(request):
        if request.url.path.count(";") == 1:
            return httpx.Response(200, json=native)
        return httpx.Response(503)

    respx.get(url__startswith=f"{BASE}/route/v1/driving/").mock(side_effect=handler)
    routes = OsrmProvider(BASE).routes(O, D)
    assert len(routes) == 1


# ------------------------------------------------------------------ http client
@respx.mock
def test_request_json_retries_transient_errors_then_succeeds():
    route = respx.get("https://api.test/x").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectTimeout("t"),
            httpx.Response(200, json={"a": 1}),
        ]
    )
    assert request_json("GET", "https://api.test/x", service="test") == {"a": 1}
    assert route.call_count == 3


@respx.mock
def test_request_json_gives_up_after_bounded_retries():
    route = respx.get("https://api.test/x").mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError) as err:
        request_json("GET", "https://api.test/x", service="test", retries=2)
    assert route.call_count == 3
    assert err.value.status == 500


@respx.mock
def test_request_json_does_not_retry_client_errors():
    route = respx.get("https://api.test/x").mock(
        return_value=httpx.Response(400, json={"reason": "bad lat"})
    )
    with pytest.raises(UpstreamError) as err:
        request_json("GET", "https://api.test/x", service="test")
    assert route.call_count == 1
    assert "bad lat" in str(err.value)


@respx.mock
def test_request_json_invalid_json():
    respx.get("https://api.test/x").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(UpstreamError):
        request_json("GET", "https://api.test/x", service="test")
