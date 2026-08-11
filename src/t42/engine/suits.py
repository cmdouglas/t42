"""Suit membership and ranking (DESIGN.md §5, "Domino & suit logic").

A tile's suit is not a property of the tile alone: it depends on the trump for the hand and on the
per-game ``doubles_are_own_suit`` variant, so every function here takes both.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

from .config import RuleConfig
from .dominoes import Domino


class Suit(IntEnum):
    """The seven number suits, plus doubles as a suit of its own under that variant."""

    BLANKS = 0
    ACES = 1
    DEUCES = 2
    TREYS = 3
    FOURS = 4
    FIVES = 5
    SIXES = 6
    DOUBLES = 7


NUMBER_SUITS: Final[tuple[Suit, ...]] = tuple(Suit(pips) for pips in range(7))

#: Trump for the hand: a suit, or ``None`` for no-trump contracts such as nello and sevens.
type Trump = Suit | None

#: Rank of a double within its own number suit - above every non-double in that suit.
_DOUBLE_RANK: Final = 7


def is_trump(domino: Domino, trump: Trump, config: RuleConfig) -> bool:
    """Whether ``domino`` is a trump tile.

    Under ``doubles_are_own_suit`` a double belongs to the doubles suit only, so ``5-5`` is not
    trump when fives are trump - it is trump only when doubles themselves are trump.
    """
    if trump is None:
        return False
    if trump is Suit.DOUBLES:
        if not config.doubles_are_own_suit:
            raise ValueError("doubles cannot be trump unless doubles_are_own_suit is enabled")
        return domino.is_double
    if config.doubles_are_own_suit and domino.is_double:
        return False
    return trump in domino.ends


def led_suit(domino: Domino, trump: Trump, config: RuleConfig) -> Suit:
    """The suit ``domino`` establishes when it is led.

    A non-trump tile belongs to both of its ends; led, it calls for its higher end.
    """
    if is_trump(domino, trump, config):
        assert trump is not None  # is_trump is False for no-trump
        return trump
    if config.doubles_are_own_suit and domino.is_double:
        return Suit.DOUBLES
    return Suit(domino.high)


def belongs_to(domino: Domino, suit: Suit, config: RuleConfig) -> bool:
    """Whether ``domino`` is a member of ``suit``, ignoring trump."""
    if suit is Suit.DOUBLES:
        return config.doubles_are_own_suit and domino.is_double
    if config.doubles_are_own_suit and domino.is_double:
        return False
    return suit in domino.ends


def follows(domino: Domino, suit: Suit, trump: Trump, config: RuleConfig) -> bool:
    """Whether playing ``domino`` follows a lead of ``suit``.

    Trump tiles follow trump and nothing else, even though they carry a second end.
    """
    if is_trump(domino, trump, config):
        return suit == trump
    return belongs_to(domino, suit, config)


def rank_in_suit(domino: Domino, suit: Suit, config: RuleConfig) -> int:
    """Rank of ``domino`` within ``suit``; higher beats lower. Only meaningful within one suit.

    Within a number suit the double is highest and the rest rank by their off end. Within the
    doubles suit, ``6-6`` is highest down to ``0-0``.
    """
    if not belongs_to(domino, suit, config):
        raise ValueError(f"{domino} is not in suit {suit.name}")
    if suit is Suit.DOUBLES:
        return domino.high
    if domino.is_double:
        return _DOUBLE_RANK
    return domino.low if domino.high == suit else domino.high
