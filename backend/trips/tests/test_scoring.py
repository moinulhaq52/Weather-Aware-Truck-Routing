import pytest

from trips.domain.scoring import owned_miles, rank, recommendation_reason, summarize, why_not_chosen
from trips.domain.types import Checkpoint, LatLon, RiskAssessment, RiskLevel, RouteSummary

R = RiskLevel


def cp(i, d, level):
    risk = None if level is None else RiskAssessment(level, level, R.LOW, R.LOW, None, ())
    return Checkpoint(index=i, distance_mi=d, point=LatLon(0, 0), eta=0, risk=risk)


def summary(no_travel=0.0, severe=0.0, high=0.0, avg=0.0, hours=10.0):
    by = dict.fromkeys(R, 0.0)
    by[R.NO_TRAVEL], by[R.SEVERE], by[R.HIGH] = no_travel, severe, high
    return RouteSummary(
        distance_mi=500,
        duration_s=hours * 3600,
        miles_by_level=by,
        unknown_miles=0,
        avg_risk=avg,
        max_level=R.LOW,
    )


# ------------------------------------------------------------ attribution
def test_owned_miles_sum_to_route_length_and_split_halfway():
    miles = owned_miles([0, 25, 50, 75, 100, 110], 110)
    assert sum(miles) == pytest.approx(110)
    assert miles == pytest.approx([12.5, 25, 25, 25, 17.5, 5])


def test_owned_miles_single_checkpoint():
    assert owned_miles([0], 0) == [0]


def test_summarize_miles_by_level_and_weighted_average():
    cps = [cp(0, 0, R.LOW), cp(1, 50, R.SEVERE), cp(2, 100, R.LOW)]
    s = summarize(cps, 100, 7200)
    assert s.miles_by_level[R.LOW] == pytest.approx(50)
    assert s.miles_by_level[R.SEVERE] == pytest.approx(50)
    assert sum(s.miles_by_level.values()) == pytest.approx(100)
    assert s.avg_risk == pytest.approx(1.5)  # (0*50 + 3*50) / 100
    assert s.max_level == R.SEVERE
    assert not s.no_travel


def test_summarize_unknown_forecast_is_excluded_from_average():
    cps = [cp(0, 0, R.HIGH), cp(1, 100, None)]
    s = summarize(cps, 100, 3600)
    assert s.unknown_miles == pytest.approx(50)
    assert s.avg_risk == pytest.approx(2.0)


# ------------------------------------------------------------ ranking: one test per tie-breaker
def test_no_travel_beats_everything_else():
    a = summary(no_travel=5, severe=0, hours=5)
    b = summary(no_travel=0, severe=100, high=100, avg=3, hours=20)
    assert rank([a, b]) == [1, 0]


def test_fewest_severe_miles_first():
    a = summary(severe=10, high=0, avg=0.5, hours=5)
    b = summary(severe=0, high=200, avg=2.0, hours=9)
    assert rank([a, b]) == [1, 0]


def test_fewest_high_miles_second():
    a = summary(severe=0, high=40, avg=0.5, hours=5)
    b = summary(severe=0, high=10, avg=1.5, hours=9)
    assert rank([a, b]) == [1, 0]


def test_lowest_average_risk_third():
    a = summary(severe=5, high=5, avg=0.9, hours=5)
    b = summary(severe=5, high=5, avg=0.4, hours=9)
    assert rank([a, b]) == [1, 0]


def test_shortest_time_last():
    a = summary(avg=0.2, hours=12)
    b = summary(avg=0.2, hours=10)
    c = summary(avg=0.2, hours=11)
    assert rank([a, b, c]) == [1, 2, 0]


def test_tolerance_prevents_float_noise_deciding():
    # 0.2 mi more Severe is within tolerance, so the faster route wins on time.
    a = summary(severe=10.2, hours=8)
    b = summary(severe=10.0, hours=9)
    assert rank([a, b]) == [0, 1]


def test_full_ordering_is_deterministic_for_identical_routes():
    s = summary()
    assert rank([s, s, s]) == [0, 1, 2]


# ------------------------------------------------------------ reason text
def test_reason_names_the_deciding_criterion():
    sums = [summary(severe=30), summary(severe=0, high=50)]
    order = rank(sums)
    text = recommendation_reason(sums, order, ["Route A", "Route B"])
    assert text.startswith("Route B has the fewest Severe miles")
    assert "0.0 mi vs 30 mi for Route A" in text


def test_reason_when_all_routes_no_travel():
    sums = [summary(no_travel=20), summary(no_travel=40)]
    text = recommendation_reason(sums, rank(sums), ["A", "B"])
    assert "Every route crosses No Travel" in text


def test_reason_single_route():
    assert "Only one" in recommendation_reason([summary()], [0], ["A"])


def test_reason_explains_why_fastest_route_lost():
    sums = [summary(severe=50, hours=8), summary(high=10, hours=9), summary(high=20, hours=10)]
    text = recommendation_reason(sums, rank(sums), ["A", "B", "C"])
    assert text.startswith("B has the fewest High miles")
    assert "A is faster but has more Severe miles (50 mi vs 0.0 mi)" in text


def test_same_exposure_on_longer_route_does_not_beat_faster_route():
    # Real case (Chicago -> Seattle): equal 50 Moderate miles; the longer route has a marginally
    # lower average only because the exposure is diluted over more miles.
    a = summary(avg=50 / 2070, hours=36.0)
    c = summary(avg=50 / 2173, hours=41.6)
    assert rank([a, c]) == [0, 1]


def test_why_not_chosen_names_the_losing_criterion():
    best, other = summary(high=10, hours=9), summary(severe=50, hours=8)
    assert (
        why_not_chosen(best, other, "Route B") == "More Severe miles than Route B: 50 mi vs 0.0 mi."
    )
    assert "Ties with Route B" in why_not_chosen(best, best, "Route B")
