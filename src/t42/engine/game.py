"""Engine entry points (DESIGN.md §3): state + proposed move in, new state or error out.

Handlers call only this module and :mod:`t42.engine.projection`; everything else is internal to
the engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from random import Random

from .config import RuleConfig
from .moves import Move
from .state import GameId, GameState, PlayerId, Seat


def new_game(
    game_id: GameId,
    players: Mapping[Seat, PlayerId],
    config: RuleConfig,
    *,
    rng: Random,
) -> GameState:
    """Create a game and deal the first hand.

    ``rng`` is injected rather than taken from module state so deals are reproducible in tests and
    the engine stays free of ambient randomness.
    """
    raise NotImplementedError("Phase 0: game setup and dealing")


def apply_move(state: GameState, move: Move) -> GameState:
    """Validate ``move`` against ``state`` and return the resulting state.

    Dispatches to the bidding machine, the declaration step or the trick engine according to the
    current phase. Raises :class:`~t42.engine.errors.RulesError` on any rejection; the caller
    persists the resulting state only when this returns.
    """
    raise NotImplementedError("Phase 0: move dispatch")


def legal_moves(state: GameState, player_id: PlayerId) -> tuple[Move, ...]:
    """Every move ``player_id`` may make right now; empty when it is not their turn."""
    raise NotImplementedError("Phase 0: move dispatch")
