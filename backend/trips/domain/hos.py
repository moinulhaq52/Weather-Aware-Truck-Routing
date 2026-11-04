"""Extra E5: FMCSA Hours-of-Service breaks for property-carrying drivers (simplified).

Modelled rules (49 CFR 395.3):
- a **30-minute break** after 8 cumulative hours of driving without one;
- after **11 hours of driving**, **10 consecutive hours off duty** (which also resets the 8-hour
  break clock).

Deliberately not modelled: the 14-hour on-duty window and on-duty-not-driving time (loading,
fuel, inspections), the 60/70-hour weekly limits and the sleeper-berth split. Only driving time
is known from the routing API, so these would be guesses. The schedule assumes a fresh driver
at departure.

``hos_schedule`` produces the stops for a given amount of driving; ``drive_to_clock`` turns
cumulative driving seconds into elapsed clock seconds, and plugs into
``domain.sampling.place_checkpoints`` so ETAs (and so the forecast hour used) include the stops.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

HOUR = 3600
BREAK_AFTER_DRIVING_S = 8 * HOUR
BREAK_S = 30 * 60
MAX_DRIVING_PER_SHIFT_S = 11 * HOUR
REST_S = 10 * HOUR


@dataclass(frozen=True, slots=True)
class Stop:
    kind: str  # "break" | "rest"
    at_drive_s: float  # cumulative driving time when the stop starts
    duration_s: float

    @property
    def label(self) -> str:
        return "30-min break" if self.kind == "break" else "10-h rest"


def hos_schedule(total_drive_s: float) -> list[Stop]:
    """Mandatory stops for a trip with ``total_drive_s`` seconds of driving.

    No stop is scheduled at (or after) arrival: a limit reached exactly on arrival needs none.
    """
    if total_drive_s < 0:
        raise ValueError("total_drive_s must be non-negative")
    stops: list[Stop] = []
    driven = since_break = in_shift = 0.0
    while True:
        step = min(BREAK_AFTER_DRIVING_S - since_break, MAX_DRIVING_PER_SHIFT_S - in_shift)
        if driven + step >= total_drive_s:
            return stops
        driven += step
        since_break += step
        in_shift += step
        if in_shift >= MAX_DRIVING_PER_SHIFT_S:
            stops.append(Stop("rest", driven, REST_S))
            in_shift = since_break = 0.0
        else:
            stops.append(Stop("break", driven, BREAK_S))
            since_break = 0.0


def make_drive_to_clock(stops: Sequence[Stop]) -> Callable[[float], float]:
    """Clock seconds elapsed after ``drive_s`` seconds of driving, including stops taken so far.

    A stop counts once driving time has *passed* its start, so the point where the driver pulls
    over gets the arrival ETA, and anything after it is shifted by the stop's duration.
    """

    def drive_to_clock(drive_s: float) -> float:
        return drive_s + sum(s.duration_s for s in stops if s.at_drive_s < drive_s)

    return drive_to_clock
