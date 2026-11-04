"""Route summaries and the recommendation.

Mile attribution (UNDERSTANDING A-8): each checkpoint "owns" the stretch of road closer to it than
to any other checkpoint: half-way back to the previous one and half-way on to the next. The owned
miles are credited to that checkpoint's risk level, so per-level miles always sum to the route
length, whatever the sampling interval.

Ranking (brief + A-10/A-11), best first:

    1. fewest No Travel miles   (not in the brief's list, but strictly worse than Severe)
    2. fewest Severe miles
    3. fewest High miles
    4. lowest average risk      (distance-weighted, Low=0 … No Travel=4)
    5. shortest travel time

Comparisons use tolerances so float noise can't decide the winner. Ranking is done by repeated
lexicographic *selection* (filter to the candidates tied on the best value of each criterion in
turn) rather than sorting with a tolerance comparator, which would not be transitive.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .types import Checkpoint, RiskLevel, RouteSummary

MILES_TOLERANCE = 0.5
# 0.05 ≈ 5% of the route one level worse. Smaller differences are noise from spreading the same
# exposure over a longer route, and must not beat hours of extra driving.
AVG_RISK_TOLERANCE = 0.05
DURATION_TOLERANCE_S = 60.0


def owned_miles(distances: Sequence[float], total_mi: float) -> list[float]:
    """Length of road attributed to each checkpoint (nearest-checkpoint rule)."""
    n = len(distances)
    if n == 0:
        return []
    if n == 1:
        return [total_mi]
    out = []
    for i, d in enumerate(distances):
        lo = 0.0 if i == 0 else (distances[i - 1] + d) / 2
        hi = total_mi if i == n - 1 else (d + distances[i + 1]) / 2
        out.append(max(0.0, hi - lo))
    return out


def summarize(
    checkpoints: Sequence[Checkpoint], distance_mi: float, duration_s: float
) -> RouteSummary:
    miles = owned_miles([c.distance_mi for c in checkpoints], distance_mi)
    by_level = dict.fromkeys(RiskLevel, 0.0)
    unknown = 0.0
    weighted = 0.0
    for cp, m in zip(checkpoints, miles, strict=True):
        if cp.risk is None:
            unknown += m
            continue
        by_level[cp.risk.level] += m
        weighted += int(cp.risk.level) * m
    known = distance_mi - unknown
    levels = [c.risk.level for c in checkpoints if c.risk is not None]
    return RouteSummary(
        distance_mi=distance_mi,
        duration_s=duration_s,
        miles_by_level=by_level,
        unknown_miles=unknown,
        avg_risk=weighted / known if known > 0 else 0.0,
        max_level=max(levels) if levels else None,
    )


@dataclass(frozen=True, slots=True)
class Criterion:
    key: str
    label: str  # "fewest Severe miles": what the winner has
    worse: str  # "more Severe miles": what a beaten route has
    value: Callable[[RouteSummary], float]
    tolerance: float
    fmt: Callable[[float], str]


def _mi(x: float) -> str:
    return f"{x:,.0f} mi" if x >= 10 else f"{x:,.1f} mi"


def _hours(s: float) -> str:
    h, m = divmod(round(s / 60), 60)
    return f"{h} h {m:02d} min"


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "no_travel_mi",
        "fewest No Travel miles",
        "more No Travel miles",
        lambda s: s.miles_by_level[RiskLevel.NO_TRAVEL],
        MILES_TOLERANCE,
        _mi,
    ),
    Criterion(
        "severe_mi",
        "fewest Severe miles",
        "more Severe miles",
        lambda s: s.miles_by_level[RiskLevel.SEVERE],
        MILES_TOLERANCE,
        _mi,
    ),
    Criterion(
        "high_mi",
        "fewest High miles",
        "more High miles",
        lambda s: s.miles_by_level[RiskLevel.HIGH],
        MILES_TOLERANCE,
        _mi,
    ),
    Criterion(
        "avg_risk",
        "lowest average risk",
        "a higher average risk",
        lambda s: s.avg_risk,
        AVG_RISK_TOLERANCE,
        lambda x: f"{x:.2f}",
    ),
    Criterion(
        "duration",
        "shortest travel time",
        "a longer travel time",
        lambda s: s.duration_s,
        DURATION_TOLERANCE_S,
        _hours,
    ),
)


def _select_best(candidates: list[int], summaries: Sequence[RouteSummary]) -> int:
    for c in CRITERIA:
        best = min(c.value(summaries[i]) for i in candidates)
        candidates = [i for i in candidates if c.value(summaries[i]) <= best + c.tolerance]
        if len(candidates) == 1:
            return candidates[0]
    # Still tied on everything: exact duration, then input order (stable and deterministic).
    return min(candidates, key=lambda i: (summaries[i].duration_s, i))


def rank(summaries: Sequence[RouteSummary]) -> list[int]:
    """Indices of ``summaries`` ordered best → worst."""
    remaining = list(range(len(summaries)))
    order = []
    while remaining:
        best = _select_best(remaining, summaries)
        order.append(best)
        remaining.remove(best)
    return order


def deciding_criterion(winner: RouteSummary, other: RouteSummary) -> Criterion | None:
    """The first criterion on which ``winner`` beats ``other`` by more than the tolerance."""
    for c in CRITERIA:
        a, b = c.value(winner), c.value(other)
        if a < b - c.tolerance:
            return c
        if a > b + c.tolerance:  # pragma: no cover - cannot happen when winner ranks first
            return None
    return None


def recommendation_reason(
    summaries: Sequence[RouteSummary], order: Sequence[int], labels: Sequence[str]
) -> str:
    """One plain-English sentence explaining why the top route was chosen."""
    if not order:
        return "No routes to compare."
    best = summaries[order[0]]
    prefix = ""
    if best.no_travel:
        prefix = (
            "Every route crosses No Travel conditions at this departure time; "
            "consider leaving at a different time. Least-bad option: "
        )
    if len(order) == 1:
        return prefix + "Only one distinct route was available."
    runner = summaries[order[1]]
    c = deciding_criterion(best, runner)
    if c is None:
        return prefix + "All options score the same; chose the first route."
    text = (
        f"{prefix}{labels[order[0]]} has the {c.label}: "
        f"{c.fmt(c.value(best))} vs {c.fmt(c.value(runner))} for {labels[order[1]]}."
    )
    # If the fastest route lost (and wasn't the runner-up already explained), say why.
    fastest = min(order, key=lambda i: summaries[i].duration_s)
    if fastest not in order[:2] and summaries[fastest].duration_s < best.duration_s:
        fc = deciding_criterion(best, summaries[fastest])
        if fc is not None and fc.key != "duration":
            text += (
                f" {labels[fastest]} is faster but has {fc.worse} "
                f"({fc.fmt(fc.value(summaries[fastest]))} vs {fc.fmt(fc.value(best))})."
            )
    return text


def why_not_chosen(winner: RouteSummary, other: RouteSummary, winner_label: str) -> str | None:
    """Extra E2: one line explaining why ``other`` lost to the recommended route."""
    c = deciding_criterion(winner, other)
    if c is None:
        return f"Ties with {winner_label} on every criterion; {winner_label} was listed first."
    return (
        f"{c.worse[0].upper()}{c.worse[1:]} than {winner_label}: "
        f"{c.fmt(c.value(other))} vs {c.fmt(c.value(winner))}."
    )
