from __future__ import annotations

import pytest

from t42.engine.config import RuleConfig
from t42.engine.contracts import get
from t42.engine.dominoes import Domino
from t42.engine.errors import IllegalMove
from t42.engine.state import Bid, Seat

SPLASH = get("splash")
DOUBLES = tuple(Domino(n, n) for n in range(7))


def test_requires_two_marks() -> None:
    with pytest.raises(IllegalMove, match="marks"):
        SPLASH.validate_bid(
            Bid(bidder=Seat.NORTH, contract="splash", marks=1), DOUBLES[:3], RuleConfig()
        )


def test_requires_at_least_three_doubles() -> None:
    weak_hand = (*DOUBLES[:2], Domino(6, 5), Domino(6, 4), Domino(5, 4), Domino(4, 3), Domino(3, 1))
    with pytest.raises(IllegalMove, match="doubles"):
        SPLASH.validate_bid(
            Bid(bidder=Seat.NORTH, contract="splash", marks=2), weak_hand, RuleConfig()
        )


def test_three_doubles_and_two_marks_is_legal() -> None:
    hand = (*DOUBLES[:3], Domino(6, 5), Domino(6, 4), Domino(5, 4), Domino(4, 3))
    SPLASH.validate_bid(Bid(bidder=Seat.NORTH, contract="splash", marks=2), hand, RuleConfig())


def test_no_partner_confirmation_needed_unlike_plunge() -> None:
    assert not SPLASH.requires_partner_confirmation()
