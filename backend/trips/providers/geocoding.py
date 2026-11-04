"""Place search for the origin/destination inputs.

Photon (komoot) is designed for search-as-you-type, which Nominatim's usage policy forbids, so
Photon is primary and Nominatim is only a fallback when Photon fails. Results are biased toward
the continental US (the app's target market) but not restricted to it. Answers are cached for a
day per normalised query, which also shields both free services from repeated keystrokes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

from django.core.cache import cache

from .http import UpstreamError, request_json

logger = logging.getLogger(__name__)

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
US_BIAS = {"lat": 39.8, "lon": -98.6}
CACHE_TTL_S = 24 * 3600
MAX_RESULTS = 6


@dataclass(frozen=True, slots=True)
class Place:
    label: str
    lat: float
    lon: float
    kind: str  # e.g. "city", "street", "house"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_query(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip().lower()


def search(q: str) -> list[Place]:
    key = "geo:" + hashlib.sha1(normalise_query(q).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        places = _photon(q)
    except UpstreamError as exc:
        logger.info("Photon failed (%s); falling back to Nominatim", exc)
        places = _nominatim(q)
    cache.set(key, places, CACHE_TTL_S)
    return places


def _photon(q: str) -> list[Place]:
    body = request_json(
        "GET",
        PHOTON_URL,
        service="geocoding",
        params={"q": q, "limit": MAX_RESULTS, "lang": "en", **US_BIAS},
        retries=1,
    )
    return parse_photon(body)


def _nominatim(q: str) -> list[Place]:
    body = request_json(
        "GET",
        NOMINATIM_URL,
        service="geocoding",
        params={"q": q, "format": "jsonv2", "limit": MAX_RESULTS},
        retries=1,
        min_interval=1.0,  # Nominatim policy: max 1 request per second
    )
    return parse_nominatim(body)


def parse_photon(body: dict[str, Any]) -> list[Place]:
    places: list[Place] = []
    seen: set[str] = set()
    for f in body.get("features", []):
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) != 2:
            continue
        props = f.get("properties") or {}
        label = _photon_label(props)
        if not label or label in seen:
            continue
        seen.add(label)
        places.append(
            Place(
                label=label, lat=float(coords[1]), lon=float(coords[0]), kind=props.get("type", "")
            )
        )
    return places


def _photon_label(p: dict[str, Any]) -> str:
    street = " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
    parts = [p.get("name"), street, p.get("city"), p.get("state")]
    if p.get("countrycode", "").upper() != "US":
        parts.append(p.get("country"))
    out: list[str] = []
    for part in parts:
        if part and part not in out:
            out.append(part)
    return ", ".join(out)


def parse_nominatim(body: list[dict[str, Any]]) -> list[Place]:
    places = []
    for r in body if isinstance(body, list) else []:
        try:
            places.append(
                Place(
                    label=str(r["display_name"]),
                    lat=float(r["lat"]),
                    lon=float(r["lon"]),
                    kind=str(r.get("type", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return places
