"""Extra E3: storm simulation and recorded-route demo mode."""

import pytest
from rest_framework.test import APIClient

from trips.domain.geo import haversine_mi
from trips.domain.types import LatLon
from trips.providers.demo import FixtureRouting, StormScenarioWeather, fixture_key
from trips.providers.http import UpstreamError
from trips.services import planner
from trips.services.planner import PlanRequest, plan_trip

from .helpers import straight_route
from .test_planner import NOW, FakeRouting, three_routes

DALLAS, DENVER = LatLon(32.7767, -96.797), LatLon(39.7392, -104.9903)
DEP = NOW + 3600


def test_storm_core_is_severe_and_far_field_is_calm():
    s = StormScenarioWeather(DALLAS, DENVER, DEP)
    t = DEP + 10 * 3600
    wind, _, rain, snow = s.conditions(s.center(t), t)
    assert wind >= 45  # Severe at the core (No Travel for heavy loads)
    assert rain + snow > 0.5
    far = LatLon(s.center(t).lat, s.center(t).lon + 10)
    assert s.conditions(far, t)[0] < 25  # Low wind far away


def test_storm_moves_and_decays():
    s = StormScenarioWeather(DALLAS, DENVER, DEP)
    assert haversine_mi(s.center(DEP), s.center(DEP + 10 * 3600)) == pytest.approx(120, rel=0.01)
    assert s.intensity(DEP + 40 * 3600) == 0


def test_storm_is_deterministic():
    a = StormScenarioWeather(DALLAS, DENVER, DEP).hourly([DALLAS, DENVER], DEP, DEP + 7200)
    b = StormScenarioWeather(DALLAS, DENVER, DEP).hourly([DALLAS, DENVER], DEP, DEP + 7200)
    assert a.series == b.series


def test_simulated_plan_is_labelled_and_uses_real_rules():
    routes = three_routes()
    o, d = routes[0].points[0], routes[0].points[-1]
    req = PlanRequest(o, d, DEP, 35_000, 25, simulate_storm=True)
    out = plan_trip(req, FakeRouting(routes), StormScenarioWeather(o, d, DEP), now=NOW)
    assert out["meta"]["weather_source"] == "simulated"
    assert out["warnings"][0].startswith("Weather is SIMULATED")
    levels = {c["risk"]["label"] for r in out["routes"] for c in r["checkpoints"] if c["risk"]}
    assert len(levels) > 1  # the storm produces a mix of risk levels


def test_fixture_routing_replays_recorded_example_and_falls_back():
    fallback = FakeRouting([straight_route(100)])
    routing = FixtureRouting(fallback)
    assert routing.has(DALLAS, DENVER)
    recorded = routing.routes(DALLAS, DENVER)
    assert len(recorded) == 3
    assert 780 < recorded[0].distance_mi < 810
    assert len(recorded[0].seg_durations_s) == len(recorded[0].points) - 1
    assert routing.routes(LatLon(0, 0), LatLon(1, 1)) == fallback.paths


def test_fixture_key_rounds_coordinates():
    assert fixture_key(DALLAS, DENVER) == "32.78,-96.80->39.74,-104.99"


def test_demo_mode_falls_back_to_simulation_when_weather_api_fails(settings):
    settings.TRIPS = {**settings.TRIPS, "DEMO_MODE": True}

    class Down:
        def hourly(self, *a):
            raise UpstreamError("weather", "HTTP 503", 503)

    routes = three_routes()
    req = PlanRequest(routes[0].points[0], routes[0].points[-1], DEP, 20_000, 25)
    out = plan_trip(req, FakeRouting(routes), Down(), now=NOW)
    assert out["meta"]["weather_source"] == "simulated"


def test_outside_demo_mode_weather_failure_still_raises(settings):
    settings.TRIPS = {**settings.TRIPS, "DEMO_MODE": False}

    class Down:
        def hourly(self, *a):
            raise UpstreamError("weather", "HTTP 503", 503)

    routes = three_routes()
    req = PlanRequest(routes[0].points[0], routes[0].points[-1], DEP, 20_000, 25)
    with pytest.raises(UpstreamError):
        plan_trip(req, FakeRouting(routes), Down(), now=NOW)


def test_api_simulate_storm_flag(monkeypatch):
    from .test_planner import FakeWeather, body, calm

    monkeypatch.setattr(
        planner, "default_providers", lambda: (FakeRouting(three_routes()), FakeWeather(calm))
    )
    res = APIClient().post("/api/plan", body(simulate_storm=True), format="json")
    assert res.status_code == 200, res.json()
    assert res.json()["meta"]["weather_source"] == "simulated"
    assert res.json()["request"]["simulate_storm"] is True
