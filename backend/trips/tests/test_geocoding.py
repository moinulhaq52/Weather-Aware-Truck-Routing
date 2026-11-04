import httpx
import pytest
import respx
from rest_framework.test import APIClient

from trips.providers import geocoding
from trips.providers import http as http_mod

PHOTON = {
    "features": [
        {
            "geometry": {"coordinates": [-96.797, 32.7767]},
            "properties": {"name": "Dallas", "state": "Texas", "countrycode": "US", "type": "city"},
        },
        {  # duplicate label is dropped
            "geometry": {"coordinates": [-96.8, 32.78]},
            "properties": {"name": "Dallas", "state": "Texas", "countrycode": "US", "type": "city"},
        },
        {
            "geometry": {"coordinates": [-77.0365, 38.8977]},
            "properties": {
                "name": "White House",
                "housenumber": "1600",
                "street": "Pennsylvania Avenue Northwest",
                "city": "Washington",
                "state": "DC",
                "countrycode": "US",
                "type": "house",
            },
        },
        {
            "geometry": {"coordinates": [-0.1276, 51.5072]},
            "properties": {"name": "London", "country": "United Kingdom", "countrycode": "GB"},
        },
        {"geometry": {"coordinates": []}, "properties": {"name": "broken"}},
    ]
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)


def test_parse_photon_labels_and_coordinates():
    places = geocoding.parse_photon(PHOTON)
    assert [p.label for p in places] == [
        "Dallas, Texas",
        "White House, 1600 Pennsylvania Avenue Northwest, Washington, DC",
        "London, United Kingdom",
    ]
    assert (places[0].lat, places[0].lon) == (32.7767, -96.797)


def test_parse_nominatim_skips_bad_rows():
    body = [{"display_name": "Denver, CO", "lat": "39.7", "lon": "-104.9"}, {"lat": "x"}]
    assert [p.label for p in geocoding.parse_nominatim(body)] == ["Denver, CO"]


@respx.mock
def test_search_falls_back_to_nominatim_and_caches():
    photon = respx.get(geocoding.PHOTON_URL).mock(return_value=httpx.Response(502))
    nomi = respx.get(geocoding.NOMINATIM_URL).mock(
        return_value=httpx.Response(
            200, json=[{"display_name": "Denver", "lat": "39.7", "lon": "-105"}]
        )
    )
    assert geocoding.search("Denver")[0].label == "Denver"
    assert geocoding.search("  denver ")[0].label == "Denver"  # normalised query hits the cache
    assert nomi.call_count == 1
    assert photon.call_count == 2  # 1 retry, then fallback


@respx.mock
def test_geocode_endpoint():
    respx.get(geocoding.PHOTON_URL).mock(return_value=httpx.Response(200, json=PHOTON))
    res = APIClient().get("/api/geocode", {"q": "dallas"})
    assert res.status_code == 200
    assert res.json()["results"][0] == {
        "label": "Dallas, Texas",
        "lat": 32.7767,
        "lon": -96.797,
        "kind": "city",
    }


def test_geocode_endpoint_validates_query():
    res = APIClient().get("/api/geocode", {"q": "a"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_input"


@respx.mock
def test_geocode_endpoint_upstream_down():
    respx.get(geocoding.PHOTON_URL).mock(return_value=httpx.Response(503))
    respx.get(geocoding.NOMINATIM_URL).mock(return_value=httpx.Response(503))
    res = APIClient().get("/api/geocode", {"q": "dallas"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_unavailable"


@respx.mock
def test_geocode_is_rate_limited(monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", {"geocode": "2/min"})
    respx.get(geocoding.PHOTON_URL).mock(return_value=httpx.Response(200, json=PHOTON))
    client = APIClient()
    codes = [client.get("/api/geocode", {"q": f"dallas {i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    assert client.get("/api/geocode", {"q": "x y"}).json()["error"]["code"] == "rate_limited"
