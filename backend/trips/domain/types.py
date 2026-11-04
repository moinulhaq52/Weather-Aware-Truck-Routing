"""Core domain types shared by every layer.

Conventions used throughout the domain package:
- Distances are in **miles**, speeds in **mph**, precipitation rates in **inches per hour**.
- Times are **UTC epoch seconds** (ints/floats). Time zones are a presentation concern only.
- Coordinates are ``LatLon(lat, lon)``. Providers that speak GeoJSON (``[lon, lat]``) convert at the
  edge so the order can never be mixed up inside the domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    """Ordered risk levels. The integer value doubles as the numeric risk score (0–4)."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Weather:
    """Forecast conditions at one place for one forecast hour."""

    wind_mph: float  # sustained 10 m wind speed (used for classification, see UNDERSTANDING A-4)
    gust_mph: float | None  # informational only
    rain_in_hr: float  # liquid precipitation (rain + showers) over the hour
    snow_in_hr: float  # snowfall depth over the hour
    valid_time: int  # epoch seconds of the forecast row used


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel  # overall = worst condition after load rules
    wind_level: RiskLevel  # wind after load rules
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_rule: str | None  # description of the load rule that raised the level, if any
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RoutePath:
    """A drivable route from the routing provider.

    ``points`` is the full-resolution polyline. ``seg_durations_s[i]`` is the travel time for the
    segment ``points[i] -> points[i + 1]``, so ``len(seg_durations_s) == len(points) - 1``.
    """

    points: tuple[LatLon, ...]
    seg_durations_s: tuple[float, ...]
    distance_mi: float
    duration_s: float
    label: str = ""
    source: str = "native"  # "native" alternative or "via" (synthesised through a via-point)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    index: int
    distance_mi: float  # from the origin, along the route
    point: LatLon
    eta: float  # epoch seconds
    weather: Weather | None = None
    risk: RiskAssessment | None = None


@dataclass(frozen=True, slots=True)
class RouteSummary:
    distance_mi: float
    duration_s: float
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float  # miles whose checkpoint had no forecast
    avg_risk: float  # distance-weighted mean of risk scores over miles with a forecast
    max_level: RiskLevel | None

    @property
    def no_travel(self) -> bool:
        return self.miles_by_level.get(RiskLevel.NO_TRAVEL, 0.0) > 0
