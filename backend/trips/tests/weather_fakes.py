"""Fake Open-Meteo responses (shape verified against the live API)."""

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx

Conditions = Callable[[float, float, int], tuple[float, float, float]]


def calm(lat, lon, t):
    return (5.0, 0.0, 0.0)


def open_meteo_handler(conditions: Conditions = calm, calls: list | None = None):
    """respx side-effect that answers a POST like Open-Meteo, using ``conditions(lat, lon, t)``.

    ``conditions`` returns (wind_mph, rain_in_hr, snow_in_hr); showers are always 0.
    """

    def handler(request: httpx.Request):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if calls is not None:
            calls.append(form)
        lats = [float(x) for x in form["latitude"].split(",")]
        lons = [float(x) for x in form["longitude"].split(",")]
        d0 = date.fromisoformat(form["start_date"])
        d1 = date.fromisoformat(form["end_date"])
        t0 = int(datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc).timestamp())
        hours = ((d1 - d0) + timedelta(days=1)).days * 24
        times = [t0 + h * 3600 for h in range(hours)]
        out = []
        for lat, lon in zip(lats, lons, strict=True):
            rows = [conditions(lat, lon, t) for t in times]
            out.append(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "hourly_units": {"wind_speed_10m": "mp/h", "rain": "inch", "snowfall": "inch"},
                    "hourly": {
                        "time": times,
                        "wind_speed_10m": [r[0] for r in rows],
                        "wind_gusts_10m": [r[0] * 1.4 for r in rows],
                        "rain": [r[1] for r in rows],
                        "showers": [0.0 for _ in rows],
                        "snowfall": [r[2] for r in rows],
                    },
                }
            )
        return httpx.Response(200, json=out if len(out) > 1 else out[0])

    return handler
