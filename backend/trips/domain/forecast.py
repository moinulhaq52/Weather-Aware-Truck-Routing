"""Choosing the forecast row that applies at a given ETA.

Open-Meteo hourly semantics (RESEARCH §1.2):

- ``rain``, ``showers``, ``snowfall`` and ``wind_gusts_10m`` are aggregates over the **preceding
  hour**: the row stamped 15:00 describes 14:00–15:00. A truck at a checkpoint at 14:20 is inside
  that interval, so we use the **first row stamped strictly after the ETA**. (An ETA of exactly
  15:00 uses the 16:00 row, i.e. the hour the truck is about to drive in.)
- ``wind_speed_10m`` is instantaneous at the row time, so we use the **nearest** row.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from .types import Weather

HOUR = 3600


@dataclass(frozen=True, slots=True)
class HourlySeries:
    """Hourly forecast for one location. All lists are aligned with ``times`` (epoch seconds)."""

    times: tuple[int, ...]
    wind_mph: tuple[float | None, ...]
    gust_mph: tuple[float | None, ...]
    rain_in_hr: tuple[float | None, ...]  # rain + showers
    snow_in_hr: tuple[float | None, ...]

    def __len__(self) -> int:
        return len(self.times)


def interval_row(times: tuple[int, ...], eta: float) -> int | None:
    """Index of the row whose preceding-hour interval contains ``eta``, or None if out of range."""
    i = bisect_right(times, eta)
    if i >= len(times):
        return None
    # The row must start its interval at or before eta (protects against gaps in the series).
    if times[i] - HOUR > eta:
        return None
    return i


def nearest_row(times: tuple[int, ...], eta: float) -> int | None:
    if not times or eta < times[0] - HOUR / 2 or eta > times[-1] + HOUR / 2:
        return None
    i = bisect_right(times, eta)
    if i == 0:
        return 0
    if i >= len(times):
        return len(times) - 1
    return i if (times[i] - eta) < (eta - times[i - 1]) else i - 1


def weather_at(series: HourlySeries, eta: float) -> Weather | None:
    """Forecast conditions at ``eta``; None if outside the forecast window or values are missing."""
    wi = nearest_row(series.times, eta)
    pi = interval_row(series.times, eta)
    if wi is None or pi is None:
        return None
    wind = series.wind_mph[wi]
    rain = series.rain_in_hr[pi]
    snow = series.snow_in_hr[pi]
    if wind is None or rain is None or snow is None:
        return None
    return Weather(
        wind_mph=float(wind),
        gust_mph=series.gust_mph[pi],
        rain_in_hr=float(rain),
        snow_in_hr=float(snow),
        valid_time=series.times[pi],
    )
