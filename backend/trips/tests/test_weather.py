from datetime import date

import httpx
import pytest
import respx

from trips.domain.forecast import weather_at
from trips.domain.types import LatLon
from trips.providers import http as http_mod
from trips.providers import weather as wmod
from trips.providers.http import UpstreamError
from trips.providers.weather import (
    FREE_URL,
    OpenMeteoProvider,
    cell_center,
    cell_of,
    parse_open_meteo,
    utc_dates,
)

from .weather_fakes import open_meteo_handler

DAY0 = 1_798_761_600  # 2027-01-01T00:00Z
P1, P2 = LatLon(39.74, -104.99), LatLon(32.78, -96.80)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)


def test_snapping_merges_nearby_points():
    assert cell_of(LatLon(39.741, -104.991)) == cell_of(LatLon(39.749, -104.98))
    assert cell_of(LatLon(39.74, -104.99)) != cell_of(LatLon(39.80, -104.99))
    c = cell_center(cell_of(P1))
    assert abs(c.lat - P1.lat) <= 0.025 and abs(c.lon - P1.lon) <= 0.025


def test_utc_dates_span():
    assert utc_dates(DAY0 + 3600, DAY0 + 2 * 86400 + 10) == [
        date(2027, 1, 1),
        date(2027, 1, 2),
        date(2027, 1, 3),
    ]


@respx.mock
def test_hourly_returns_series_with_units_and_combined_rain():
    def cond(lat, lon, t):
        return (30.0, 0.2, 0.6)

    respx.post(FREE_URL).mock(side_effect=open_meteo_handler(cond))
    batch = OpenMeteoProvider(api_key="").hourly([P1, P2], DAY0 + 5 * 3600, DAY0 + 30 * 3600)
    assert not batch.missing
    s = batch.at(P1)
    assert s is not None and len(s) == 48  # two whole UTC days
    w = weather_at(s, DAY0 + 10 * 3600 + 600)
    assert w is not None
    assert (w.wind_mph, w.rain_in_hr, w.snow_in_hr) == (30.0, 0.2, 0.6)


@respx.mock
def test_points_in_same_cell_are_fetched_once_and_cached():
    calls: list = []
    route = respx.post(FREE_URL).mock(side_effect=open_meteo_handler(calls=calls))
    p = OpenMeteoProvider(api_key="")
    pts = [P1, LatLon(P1.lat + 0.001, P1.lon), P2]
    p.hourly(pts, DAY0, DAY0 + 3600)
    assert route.call_count == 1
    assert len(calls[0]["latitude"].split(",")) == 2  # deduplicated to 2 cells
    second = p.hourly(pts, DAY0, DAY0 + 3600)
    assert route.call_count == 1  # fully cached
    assert second.upstream_calls == 0


@respx.mock
def test_only_missing_days_are_requested():
    calls: list = []
    respx.post(FREE_URL).mock(side_effect=open_meteo_handler(calls=calls))
    p = OpenMeteoProvider(api_key="")
    p.hourly([P1], DAY0, DAY0 + 3600)  # day 1
    p.hourly([P1], DAY0, DAY0 + 86400 + 3600)  # days 1-2 -> only day 2 fetched
    assert calls[1]["start_date"] == calls[1]["end_date"] == "2027-01-02"


@respx.mock
def test_chunking(monkeypatch):
    monkeypatch.setattr(wmod, "CHUNK_SIZE", 10)
    route = respx.post(FREE_URL).mock(side_effect=open_meteo_handler())
    pts = [LatLon(30 + i * 0.1, -100) for i in range(25)]
    batch = OpenMeteoProvider(api_key="").hourly(pts, DAY0, DAY0 + 3600)
    assert route.call_count == 3
    assert len(batch.series) == 25


@respx.mock
def test_partial_failure_marks_cells_missing(monkeypatch):
    monkeypatch.setattr(wmod, "CHUNK_SIZE", 1)
    good = open_meteo_handler()

    def flaky(request):
        return httpx.Response(503) if "32.8" in request.content.decode() else good(request)

    respx.post(FREE_URL).mock(side_effect=flaky)
    batch = OpenMeteoProvider(api_key="").hourly([P1, P2], DAY0, DAY0 + 3600)
    assert batch.at(P1) is not None
    assert batch.at(P2) is None
    assert cell_of(P2) in batch.missing


@respx.mock
def test_total_failure_raises():
    respx.post(FREE_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(UpstreamError):
        OpenMeteoProvider(api_key="").hourly([P1], DAY0, DAY0 + 3600)


@respx.mock
def test_api_key_uses_commercial_endpoint():
    route = respx.post(wmod.COMMERCIAL_URL).mock(side_effect=open_meteo_handler())
    OpenMeteoProvider(api_key="secret").hourly([P1], DAY0, DAY0 + 3600)
    assert route.called
    assert b"apikey=secret" in route.calls[0].request.content


def test_parse_handles_nulls_and_missing_hours():
    body = {
        "hourly": {
            "time": [DAY0, DAY0 + 3600],
            "wind_speed_10m": [10, None],
            "wind_gusts_10m": [15, 20],
            "rain": [None, 0.1],
            "showers": [None, 0.05],
            "snowfall": [0, 0],
        }
    }
    cell = cell_of(P1)
    rows = parse_open_meteo(body, [cell], (date(2027, 1, 1), date(2027, 1, 1)))[cell][
        date(2027, 1, 1)
    ]
    assert rows["wind"][:3] == [10.0, None, None]  # hour 2 absent -> None
    assert rows["rain"][0] is None  # both rain and showers null -> unknown, not 0
    assert rows["rain"][1] == pytest.approx(0.15)  # rain + showers


def test_parse_rejects_wrong_location_count():
    with pytest.raises(UpstreamError):
        parse_open_meteo([{}, {}], [cell_of(P1)], (date(2027, 1, 1), date(2027, 1, 1)))
