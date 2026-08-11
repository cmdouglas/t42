"""Trick play and resolution (DESIGN.md §5). Phase 0, not yet implemented.

Follow-suit legality and trick winners are pure functions of the suit logic in
:mod:`t42.engine.suits`; contract-specific restrictions (e.g. sevens) come from the active
contract strategy rather than from branches here.
"""

from __future__ import annotations

from .config import RuleConfig
from .dominoes import Domino
from .moves import PlayDomino
from .state import GameState, Seat, Trick
from .suits import Trump


def legal_plays(
    hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig
) -> tuple[Domino, ...]:
    """The tiles in ``hand`` that may legally be played to ``trick``.

    Leading, that is the whole hand; following, it is the tiles in the led suit if any are held.
    """
    raise NotImplementedError("Phase 0: trick engine")


def trick_winner(trick: Trick, trump: Trump, config: RuleConfig) -> Seat:
    """The seat that wins a completed trick: highest trump, else highest tile of the led suit."""
    raise NotImplementedError("Phase 0: trick engine")


def play(state: GameState, move: PlayDomino) -> GameState:
    """Validate and apply a domino play, closing the trick and the hand when they complete."""
    raise NotImplementedError("Phase 0: trick engine")
