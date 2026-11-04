"""Weather risk classification: the exact rules from the task brief.

Threshold table (brief) and how each boundary is resolved (UNDERSTANDING A-2):

    Condition  Low          Moderate      High          Severe        No Travel
    Wind       < 25 mph     [25, 35)      [35, 45)      [45, 55)      >= 55 mph
    Rain       < 0.10 in/hr [0.10, 0.25)  [0.25, 0.50)  [0.50, 1.00]  > 1.00
    Snow       < 0.5 in/hr  [0.5, 1.0)    [1.0, 2.0)    [2.0, 3.0]    > 3.0

The brief's ranges share endpoints (e.g. 0.25 is in both Moderate and High). A shared endpoint goes
to the *higher* level (safety-conservative), except where the brief explicitly writes ``>`` for No
Travel (rain > 1.00, snow > 3.0), which makes 1.00 / 3.0 themselves Severe.

Load rules (applied to the wind level only, and only ever raising it):

    wind >= 55 mph                        -> No Travel (any load; already in the table)
    45 <= wind < 55 and load > 30,000 lb  -> No Travel
    35 <= wind < 45 and load > 40,000 lb  -> Severe

The overall checkpoint level is the worst of the wind (after load rules), rain and snow levels.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import RiskAssessment, RiskLevel, Weather


@dataclass(frozen=True, slots=True)
class Threshold:
    """A value at or above ``value`` (strictly above if not ``inclusive``) is at least ``level``."""

    level: RiskLevel
    value: float
    inclusive: bool = True

    def reached_by(self, x: float) -> bool:
        return x >= self.value if self.inclusive else x > self.value


# Ordered from mildest to worst. Anything below the first threshold is LOW.
WIND_THRESHOLDS_MPH: tuple[Threshold, ...] = (
    Threshold(RiskLevel.MODERATE, 25),
    Threshold(RiskLevel.HIGH, 35),
    Threshold(RiskLevel.SEVERE, 45),
    Threshold(RiskLevel.NO_TRAVEL, 55),
)
RAIN_THRESHOLDS_IN_HR: tuple[Threshold, ...] = (
    Threshold(RiskLevel.MODERATE, 0.10),
    Threshold(RiskLevel.HIGH, 0.25),
    Threshold(RiskLevel.SEVERE, 0.50),
    Threshold(RiskLevel.NO_TRAVEL, 1.00, inclusive=False),
)
SNOW_THRESHOLDS_IN_HR: tuple[Threshold, ...] = (
    Threshold(RiskLevel.MODERATE, 0.5),
    Threshold(RiskLevel.HIGH, 1.0),
    Threshold(RiskLevel.SEVERE, 2.0),
    Threshold(RiskLevel.NO_TRAVEL, 3.0, inclusive=False),
)


@dataclass(frozen=True, slots=True)
class LoadRule:
    """Raise wind to ``level`` when wind is in [min_wind, max_wind) and load > min_load."""

    min_wind_mph: float
    max_wind_mph: float
    min_load_lb: float  # exclusive: the brief says "> 30,000 lb"
    level: RiskLevel
    description: str

    def applies(self, wind_mph: float, load_lb: float) -> bool:
        return self.min_wind_mph <= wind_mph < self.max_wind_mph and load_lb > self.min_load_lb


LOAD_RULES: tuple[LoadRule, ...] = (
    LoadRule(45, 55, 30_000, RiskLevel.NO_TRAVEL, "wind 45–54 mph with load over 30,000 lb"),
    LoadRule(35, 45, 40_000, RiskLevel.SEVERE, "wind 35–44 mph with load over 40,000 lb"),
)


def level_for(value: float, thresholds: tuple[Threshold, ...]) -> RiskLevel:
    """Classify one measurement against an ordered threshold table."""
    if value != value:  # NaN guard: never silently classify missing data as LOW
        raise ValueError("Cannot classify NaN")
    level = RiskLevel.LOW
    for t in thresholds:
        if t.reached_by(value):
            level = t.level
    return level


def classify_wind(wind_mph: float) -> RiskLevel:
    return level_for(wind_mph, WIND_THRESHOLDS_MPH)


def classify_rain(rain_in_hr: float) -> RiskLevel:
    return level_for(rain_in_hr, RAIN_THRESHOLDS_IN_HR)


def classify_snow(snow_in_hr: float) -> RiskLevel:
    return level_for(snow_in_hr, SNOW_THRESHOLDS_IN_HR)


def apply_load_rules(wind_mph: float, load_lb: float) -> tuple[RiskLevel, LoadRule | None]:
    """Wind level after load rules, plus the rule that raised it (``None`` if none did)."""
    base = classify_wind(wind_mph)
    for rule in LOAD_RULES:
        if rule.applies(wind_mph, load_lb) and rule.level > base:
            return rule.level, rule
    return base, None


def classify(weather: Weather, load_lb: float) -> RiskAssessment:
    """Full checkpoint assessment with human-readable reasons for every non-Low factor."""
    wind_level, rule = apply_load_rules(weather.wind_mph, load_lb)
    rain_level = classify_rain(weather.rain_in_hr)
    snow_level = classify_snow(weather.snow_in_hr)
    overall = max(wind_level, rain_level, snow_level)

    reasons: list[str] = []
    base_wind = classify_wind(weather.wind_mph)
    if base_wind > RiskLevel.LOW:
        reasons.append(f"Wind {weather.wind_mph:.0f} mph → {base_wind.label}")
    if rule is not None:
        reasons.append(f"Load rule: {rule.description} ({load_lb:,.0f} lb) → {rule.level.label}")
    if rain_level > RiskLevel.LOW:
        reasons.append(f"Rain {weather.rain_in_hr:.2f} in/hr → {rain_level.label}")
    if snow_level > RiskLevel.LOW:
        reasons.append(f"Snow {weather.snow_in_hr:.2f} in/hr → {snow_level.label}")
    if not reasons:
        reasons.append("All conditions below risk thresholds")

    return RiskAssessment(
        level=overall,
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_rule=rule.description if rule else None,
        reasons=tuple(reasons),
    )


def classify_values(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> int:
    """Fast path returning only the overall level as an int (used for the heatmap grid)."""
    wind_level, _ = apply_load_rules(wind_mph, load_lb)
    return int(max(wind_level, classify_rain(rain_in_hr), classify_snow(snow_in_hr)))
