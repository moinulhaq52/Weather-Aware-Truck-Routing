import pytest

from trips.domain.hos import BREAK_S, REST_S, hos_schedule, make_drive_to_clock
from trips.domain.sampling import place_checkpoints

from .helpers import straight_route

H = 3600


@pytest.mark.parametrize(
    ("drive_h", "expected"),
    [
        (7.9, []),
        (8.0, []),  # limit reached exactly on arrival: no stop needed
        (8.5, [("break", 8)]),
        (11.0, [("break", 8)]),
        (12.0, [("break", 8), ("rest", 11)]),
        # After the 10 h rest a new shift starts: break at 8 h into it, rest at 11 h into it.
        (24.0, [("break", 8), ("rest", 11), ("break", 19), ("rest", 22)]),
    ],
)
def test_schedule(drive_h, expected):
    stops = hos_schedule(drive_h * H)
    assert [(s.kind, s.at_drive_s / H) for s in stops] == expected


def test_drive_to_clock_adds_stops_already_passed():
    clock = make_drive_to_clock(hos_schedule(14 * H))
    assert clock(7 * H) == 7 * H
    assert clock(8 * H) == 8 * H  # arriving at the break
    assert clock(9 * H) == 9 * H + BREAK_S
    assert clock(12 * H) == 12 * H + BREAK_S + REST_S


def test_negative_driving_rejected():
    with pytest.raises(ValueError):
        hos_schedule(-1)


def test_checkpoint_etas_shift_after_rest():
    route = straight_route(780, n_points=200, speed_mph=60)  # 13 h of driving at the cap
    clock = make_drive_to_clock(hos_schedule(780 / 60 * H))
    plain = place_checkpoints(route, 50, 0, 65)
    hos = place_checkpoints(route, 50, 0, 65, drive_to_clock=clock)
    early = next(i for i, c in enumerate(plain) if c.distance_mi == 300)  # 5 h in
    late = next(i for i, c in enumerate(plain) if c.distance_mi == 750)  # 12.5 h in
    assert hos[early].eta == plain[early].eta
    assert hos[late].eta - plain[late].eta == pytest.approx(BREAK_S + REST_S)
