"""Planner + /api/plan integration tests with deterministic fake providers."""

from datetime import datetime, timezone

import httpx
import pytest
import respx
from rest_framework.test import APIClient

from trips.domain.forecast import HourlySeries
from trips.domain.types import LatLon, RoutePath
from trips.providers import http as http_mod
from trips.providers.http import UpstreamError
from trips.providers.routing import NoRouteError
from trips.providers.weather import FREE_URL, WeatherBatch, cell_of
from trips.services import planner
from trips.services.planner import PlanError, PlanRequest, plan_trip

from .helpers import straight_route
from .osrm_fakes import ok, osrm_route
from .weather_fakes import open_meteo_handler

NOW = 1_800_000_000 - (1_800_000_000 % 3600)
DEP = NOW + 2 * 3600
ORIGIN = LatLon(30.0, -100.0)


# --------------------------------------------------------------------------- fakes
class FakeRouting:
    def __init__(self, paths):
        self.paths = paths

    def routes(self, origin, destination):
        if isinstance(self.paths, Exception):
            raise self.paths
        return self.paths


class FakeWeather:
    """Weather field defined by ``conditions(lat, lon, t) -> (wind, rain, snow)``."""

    def __init__(self, conditions, missing_if=None):
        self.conditions = conditions
        self.missing_if = missing_if or (lambda p: False)
        self.calls = 0

    def hourly(self, points, start, end):
        self.calls += 1
        batch = WeatherBatch()
        t0 = int(start // 3600 * 3600)
        times = tuple(range(t0, int(end) + 3600, 3600))
        for p in points:
            c = cell_of(p)
            if self.missing_if(p):
                batch.missing.add(c)
                continue
            rows = [self.conditions(p.lat, p.lon, t) for t in times]
            batch.series[c] = HourlySeries(
                times=times,
                wind_mph=tuple(r[0] for r in rows),
                gust_mph=tuple(r[0] * 1.3 for r in rows),
                rain_in_hr=tuple(r[1] for r in rows),
                snow_in_hr=tuple(r[2] for r in rows),
            )
        return batch


def calm(lat, lon, t):
    return (5.0, 0.0, 0.0)


def three_routes():
    # Parallel due-north routes 300 mi long, ~140 mi apart; Route A is the fastest.
    return [
        straight_route(300, speed_mph=60, lon=-100.0),
        straight_route(300, speed_mph=55, lon=-97.5),
        straight_route(300, speed_mph=50, lon=-95.0),
    ]


def req(**kw):
    base = {
        "origin": ORIGIN,
        "destination": LatLon(34.34, -100.0),
        "departure": DEP,
        "load_lb": 20_000,
        "interval_mi": 25,
    }
    base.update(kw)
    return PlanRequest(**base)


def run(conditions=calm, routes=None, **kw):
    return plan_trip(
        req(**kw), FakeRouting(routes or three_routes()), FakeWeather(conditions), now=NOW
    )


# --------------------------------------------------------------------------- planner logic
def test_happy_path_shape():
    out = run()
    assert len(out["routes"]) == 3
    assert out["recommended_route_id"] == "Route A"  # all calm -> fastest wins
    assert "shortest travel time" in out["recommendation_reason"]
    r = out["routes"][0]
    assert r["rank"] == 1 and r["recommended"]
    assert len(r["checkpoints"]) == 13  # 0, 25, ..., 300
    assert r["checkpoints"][0]["eta"] == DEP
    assert r["checkpoints"][-1]["eta"] == pytest.approx(DEP + 300 * 60, abs=2)
    assert r["summary"]["miles_by_level"]["low"] == pytest.approx(300, abs=0.2)
    assert r["geometry"][0] == [-100.0, 30.0]  # GeoJSON [lon, lat]
    hm = out["heatmap"]
    assert hm["hours"] == 49 and len(hm["level"]) == 49
    assert all(len(frame) == len(hm["nodes"]) for frame in hm["level"])
    assert len(hm["core"]) == hm["grid"]["n_lat"] * hm["grid"]["n_lon"]
    assert out["warnings"] == []


def test_storm_on_fastest_route_changes_recommendation():
    def storm_on_a(lat, lon, t):
        return (48.0, 0.0, 0.0) if lon < -99 else (10.0, 0.0, 0.0)  # Severe winds on Route A

    out = run(storm_on_a)
    assert out["recommended_route_id"] == "Route B"
    assert (
        "Route A is faster but has more Severe miles (300 mi vs 0.0 mi)"
        in (out["recommendation_reason"])
    )
    a = out["routes"][0]
    assert a["summary"]["miles_by_level"]["severe"] == pytest.approx(300, abs=0.2)
    assert a["rank"] in (2, 3)
    assert a["why_not"].startswith("More Severe miles than Route B")
    assert out["routes"][1]["why_not"] is None  # the recommended route


def test_load_rule_turns_severe_into_no_travel():
    def gale(lat, lon, t):
        return (47.0, 0.0, 0.0)

    light = run(gale, load_lb=20_000)["routes"][0]["checkpoints"][3]["risk"]
    heavy = run(gale, load_lb=35_000)["routes"][0]["checkpoints"][3]["risk"]
    assert light["label"] == "Severe" and light["load_rule"] is None
    assert heavy["label"] == "No Travel" and "30,000" in heavy["load_rule"]


def test_weather_is_sampled_at_eta_not_departure():
    # A snow band 150 mi north of the origin that only exists for the first hour after departure.
    # The truck reaches it ~2.5 h later, after it has cleared, so the route must stay Low.
    band_lat = 30.0 + 150 / 69.09

    def transient_band(lat, lon, t):
        here = abs(lat - band_lat) < 0.2
        return (5.0, 0.0, 2.5 if here and t <= DEP + 3600 else 0.0)

    out = run(transient_band)
    assert all(
        c["risk"]["label"] == "Low" for r in out["routes"] for c in r["checkpoints"] if c["risk"]
    )
    # ...but the heatmap at hour 0 does show it.
    assert max(out["heatmap"]["level"][0]) == 3  # Severe snow in the band at departure


def test_departure_time_shifts_etas_into_storm():
    band_lat = 30.0 + 150 / 69.09

    def late_band(lat, lon, t):  # band appears 2-4 h after departure
        here = abs(lat - band_lat) < 0.2
        return (5.0, 0.0, 2.5 if here and DEP + 2 * 3600 <= t <= DEP + 4 * 3600 else 0.0)

    out = run(late_band)
    a = out["routes"][0]
    assert a["summary"]["miles_by_level"]["severe"] > 0
    cp = next(c for c in a["checkpoints"] if c["distance_mi"] == 150)
    assert cp["risk"]["label"] == "Severe" and cp["weather"]["snow_in_hr"] == 2.5


def test_missing_forecast_is_reported_not_treated_as_low():
    weather = FakeWeather(calm, missing_if=lambda p: p.lat > 33)
    out = plan_trip(req(), FakeRouting(three_routes()), weather, now=NOW)
    a = out["routes"][0]
    assert any(c["risk"] is None for c in a["checkpoints"])
    assert a["summary"]["unknown_miles"] > 0
    assert any("No forecast" in w for w in out["warnings"])


def test_single_weather_fetch_for_checkpoints_and_heatmap():
    weather = FakeWeather(calm)
    plan_trip(req(), FakeRouting(three_routes()), weather, now=NOW)
    assert weather.calls == 1


def test_fewer_than_three_routes_warns():
    out = run(routes=[straight_route(300)])
    assert len(out["routes"]) == 1
    assert "Only one distinct route" in out["recommendation_reason"]
    assert any("Only 1 distinct route" in w for w in out["warnings"])


def test_far_future_trip_warns_about_confidence():
    out = run(departure=NOW + 4 * 86400)
    assert any("less certain" in w for w in out["warnings"])


@pytest.mark.parametrize(
    ("kwargs", "routes", "code"),
    [
        ({"destination": ORIGIN}, None, "same_place"),
        ({}, NoRouteError("none"), "no_route"),
        ({}, [], "no_route"),
        ({}, [straight_route(3200)], "too_long"),
        ({"departure": NOW + 14.9 * 86400}, None, "beyond_forecast"),
    ],
)
def test_plan_errors(kwargs, routes, code):
    with pytest.raises(PlanError) as err:
        plan_trip(
            req(**kwargs),
            FakeRouting(three_routes() if routes is None else routes),
            FakeWeather(calm),
            now=NOW,
        )
    assert err.value.code == code


# --------------------------------------------------------------------------- HTTP API
def iso(ts, offset="-06:00"):
    dt = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
    return (
        dt.isoformat() + "Z"
        if offset == "Z"
        else datetime.fromtimestamp(ts).astimezone().isoformat()
    )


def body(**kw):
    import time as _t

    b = {
        "origin": {"lat": 30.0, "lon": -100.0, "label": "Origin"},
        "destination": {"lat": 34.34, "lon": -100.0, "label": "Dest"},
        "departure_time": iso(_t.time() + 3600),
        "load_weight_lb": 20_000,
        "interval_miles": 25,
    }
    b.update(kw)
    return b


@pytest.fixture
def fake_providers(monkeypatch):
    monkeypatch.setattr(
        planner, "default_providers", lambda: (FakeRouting(three_routes()), FakeWeather(calm))
    )


def post(data):
    return APIClient().post("/api/plan", data, format="json")


def test_api_plan_success(fake_providers):
    res = post(body())
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["recommended_route_id"] == "Route A"
    assert data["request"]["origin"]["label"] == "Origin"


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"load_weight_lb": 0}, "load_weight_lb"),
        ({"load_weight_lb": 100_000}, "load_weight_lb"),
        ({"interval_miles": 30}, "interval_miles"),
        ({"origin": {"lat": 100, "lon": 0}}, "origin"),
        ({"departure_time": "2020-01-01T00:00:00Z"}, "departure_time"),
        ({"departure_time": "2999-01-01T00:00:00Z"}, "departure_time"),
        ({"departure_time": "2026-11-04T08:00:00"}, "departure_time"),  # no UTC offset
        ({"departure_time": "tomorrow"}, "departure_time"),
    ],
)
def test_api_plan_validation(fake_providers, override, field):
    res = post(body(**override))
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "invalid_input"
    assert field in err["details"]


def test_api_plan_missing_fields(fake_providers):
    res = post({})
    assert res.status_code == 400
    assert set(res.json()["error"]["details"]) >= {"origin", "destination", "load_weight_lb"}


def test_api_plan_unprocessable(fake_providers):
    res = post(body(destination={"lat": 30.0, "lon": -100.0}))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "same_place"


def test_api_plan_upstream_failure(monkeypatch):
    class Down:
        def routes(self, o, d):
            raise UpstreamError("routing", "HTTP 503", 503)

    monkeypatch.setattr(planner, "default_providers", lambda: (Down(), FakeWeather(calm)))
    res = post(body())
    assert res.status_code == 502
    assert "Routing service" in res.json()["error"]["message"]


def test_api_plan_rate_limit_message(monkeypatch):
    class Limited:
        def hourly(self, *a):
            raise UpstreamError("weather", "weather service rate limit reached", 429)

    monkeypatch.setattr(
        planner, "default_providers", lambda: (FakeRouting(three_routes()), Limited())
    )
    res = post(body())
    assert res.status_code == 502
    assert "rate-limiting" in res.json()["error"]["message"]


@respx.mock
def test_api_plan_full_stack_with_mocked_http(monkeypatch, settings):
    """Real providers end to end, with only the HTTP layer faked."""
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    settings.TRIPS = {
        **settings.TRIPS,
        "OSRM_BASE_URL": "https://osrm.test",
        "OPEN_METEO_API_KEY": "",
    }
    route = straight_route(300, n_points=80)
    osrm = ok(osrm_route(list(route.points), summary="I 27"))
    respx.get(url__startswith="https://osrm.test/route/v1/driving/").mock(
        return_value=httpx.Response(200, json=osrm)
    )
    respx.post(FREE_URL).mock(side_effect=open_meteo_handler(lambda lat, lon, t: (30.0, 0.0, 0.0)))
    res = post(body())
    assert res.status_code == 200, res.json()
    data = res.json()
    # Native route plus via-point routes all come from the same fake, so they dedupe to one.
    assert len(data["routes"]) == 1
    assert data["routes"][0]["via"] == "I 27"
    assert data["routes"][0]["checkpoints"][1]["risk"]["label"] == "Moderate"  # 30 mph wind
    assert data["meta"]["weather_requests"] >= 1


def test_routes_are_paths():
    # Type sanity for the helper used throughout these tests.
    assert isinstance(three_routes()[0], RoutePath)


# --------------------------------------------------------------------------- extra E4
def test_departure_scan_finds_a_later_safer_start():
    # Severe wind everywhere for the first 8 h after departure, calm afterwards.
    def early_gale(lat, lon, t):
        return (48.0, 0.0, 0.0) if t < DEP + 8 * 3600 else (5.0, 0.0, 0.0)

    out = run(early_gale)
    opts = out["departure_options"]
    assert [o["offset_h"] for o in opts] == [0, 3, 6, 9, 12, 18, 24]
    best = next(o for o in opts if o["best"])
    assert best["offset_h"] == 9  # first start that misses the gale entirely (5 h trip)
    assert best["miles_by_level"]["severe"] == 0
    assert opts[0]["miles_by_level"]["severe"] > 0
    assert out["departure_advice"].startswith("Leaving 9 h later")


def test_departure_scan_keeps_planned_time_when_nothing_is_better():
    out = run()
    assert next(o for o in out["departure_options"] if o["best"])["offset_h"] == 0
    assert out["departure_advice"].startswith("Leaving at your planned time")


def test_departure_scan_needs_no_extra_weather_fetch():
    weather = FakeWeather(calm)
    plan_trip(req(), FakeRouting(three_routes()), weather, now=NOW)
    assert weather.calls == 1


def test_departure_scan_skips_offsets_beyond_the_forecast_horizon():
    out = run(departure=NOW + 14.6 * 86400)  # 5 h trip: only offsets up to ~4 h fit in 15 days
    assert [o["offset_h"] for o in out["departure_options"]] == [0, 3]


# --------------------------------------------------------------------------- extra E5
def test_hos_adds_stops_and_shifts_etas():
    long = [straight_route(780, n_points=200, speed_mph=60)]  # 13 h of driving
    plain = run(routes=long)
    hos = run(routes=long, hos=True)
    r0, r1 = plain["routes"][0], hos["routes"][0]
    assert r0["stops"] == []
    assert [s["kind"] for s in r1["stops"]] == ["break", "rest"]
    brk = r1["stops"][0]
    assert brk["distance_mi"] == pytest.approx(480, abs=1)  # 8 h at 60 mph
    assert brk["end"] - brk["start"] == 1800
    assert brk["start"] == pytest.approx(DEP + 8 * 3600, abs=2)
    assert r1["summary"]["duration_s"] - r0["summary"]["duration_s"] == pytest.approx(
        10.5 * 3600, abs=2
    )
    assert r1["checkpoints"][-1]["eta"] - r0["checkpoints"][-1]["eta"] == pytest.approx(
        10.5 * 3600, abs=2
    )
    assert hos["request"]["hos"] is True


def test_hos_changes_which_forecast_applies():
    # Snow at the destination end only from 14 h after departure: without HOS the truck arrives
    # after 13 h (clear); with a 10.5 h of stops it arrives into the snow.
    end_lat = 30.0 + 780 / 69.09

    def late_snow(lat, lon, t):
        return (5.0, 0.0, 2.5 if lat > end_lat - 1.5 and t > DEP + 14 * 3600 else 0.0)

    long = [straight_route(780, n_points=200, speed_mph=60)]
    assert run(late_snow, routes=long)["routes"][0]["summary"]["miles_by_level"]["severe"] == 0
    assert (
        run(late_snow, routes=long, hos=True)["routes"][0]["summary"]["miles_by_level"]["severe"]
        > 0
    )
