"""Risk rules from the brief, tested at and around every boundary."""

import math

import pytest

from trips.domain.risk import (
    apply_load_rules,
    classify,
    classify_rain,
    classify_snow,
    classify_values,
    classify_wind,
)
from trips.domain.types import RiskLevel as R
from trips.domain.types import Weather


def wx(wind=0.0, rain=0.0, snow=0.0, gust=None):
    return Weather(wind_mph=wind, gust_mph=gust, rain_in_hr=rain, snow_in_hr=snow, valid_time=0)


@pytest.mark.parametrize(
    ("mph", "expected"),
    [
        (0, R.LOW),
        (24.9, R.LOW),
        (25, R.MODERATE),
        (34.9, R.MODERATE),
        (35, R.HIGH),
        (44.99, R.HIGH),
        (45, R.SEVERE),
        (54.9, R.SEVERE),
        (55, R.NO_TRAVEL),
        (120, R.NO_TRAVEL),
    ],
)
def test_wind_thresholds(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, R.LOW),
        (0.099, R.LOW),
        (0.10, R.MODERATE),
        (0.249, R.MODERATE),
        (0.25, R.HIGH),  # shared endpoint goes to the higher level
        (0.499, R.HIGH),
        (0.50, R.SEVERE),
        (1.00, R.SEVERE),  # "No Travel > 1.00" -> 1.00 itself is Severe
        (1.001, R.NO_TRAVEL),
        (3.5, R.NO_TRAVEL),
    ],
)
def test_rain_thresholds(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, R.LOW),
        (0.49, R.LOW),
        (0.5, R.MODERATE),
        (0.99, R.MODERATE),
        (1.0, R.HIGH),
        (1.99, R.HIGH),
        (2.0, R.SEVERE),
        (3.0, R.SEVERE),  # "No Travel > 3.0" -> 3.0 itself is Severe
        (3.01, R.NO_TRAVEL),
    ],
)
def test_snow_thresholds(rate, expected):
    assert classify_snow(rate) == expected


@pytest.mark.parametrize(
    ("mph", "load", "expected", "rule_applied"),
    [
        # >= 55 mph: No Travel for any load (table itself, no load rule needed)
        (55, 0, R.NO_TRAVEL, False),
        (70, 80_000, R.NO_TRAVEL, False),
        # 45–54 mph + > 30,000 lb -> No Travel
        (45, 30_000, R.SEVERE, False),  # exactly 30,000 is not "> 30,000"
        (45, 30_001, R.NO_TRAVEL, True),
        (54.9, 45_000, R.NO_TRAVEL, True),
        (44.9, 45_000, R.SEVERE, True),  # falls into the 35–44 rule instead
        # 35–44 mph + > 40,000 lb -> Severe
        (35, 40_000, R.HIGH, False),
        (35, 40_001, R.SEVERE, True),
        (44.9, 40_001, R.SEVERE, True),
        (34.9, 80_000, R.MODERATE, False),  # below 35 mph no load rule applies
        # Light loads keep the table level
        (40, 10_000, R.HIGH, False),
        (50, 10_000, R.SEVERE, False),
    ],
)
def test_load_rules(mph, load, expected, rule_applied):
    level, rule = apply_load_rules(mph, load)
    assert level == expected
    assert (rule is not None) == rule_applied


def test_overall_is_worst_condition():
    a = classify(wx(wind=26, rain=0.3, snow=2.5), load_lb=10_000)
    assert (a.wind_level, a.rain_level, a.snow_level) == (R.MODERATE, R.HIGH, R.SEVERE)
    assert a.level == R.SEVERE


def test_load_rule_can_dominate_overall_level_and_is_explained():
    a = classify(wx(wind=47, rain=0.12), load_lb=35_000)
    assert a.level == R.NO_TRAVEL
    assert a.load_rule is not None
    assert any("Load rule" in r and "No Travel" in r for r in a.reasons)
    assert any(r.startswith("Wind 47 mph → Severe") for r in a.reasons)


def test_calm_weather_reason():
    a = classify(wx(), load_lb=80_000)
    assert a.level == R.LOW
    assert a.reasons == ("All conditions below risk thresholds",)


def test_gusts_do_not_affect_classification():
    assert classify(wx(wind=10, gust=70), 80_000).level == R.LOW


def test_nan_is_rejected_rather_than_treated_as_low():
    with pytest.raises(ValueError):
        classify_wind(math.nan)


def test_fast_path_matches_full_classification():
    for wind in (0, 30, 40, 50, 60):
        for rain in (0, 0.2, 0.6, 1.2):
            for snow in (0, 0.7, 2.5):
                for load in (20_000, 35_000, 45_000):
                    full = classify(wx(wind, rain, snow), load).level
                    assert classify_values(wind, rain, snow, load) == int(full)
