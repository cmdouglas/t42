"""Bidding state machine (DESIGN.md §5). Phase 0, not yet implemented.

Covers: turn order for the auction, valid numeric bids (30-42) and mark bids, which mark bids the
game's :class:`~t42.engine.config.RuleConfig` allows, pass handling, all-pass re-deal or forced
bid, and determining the declarer.
"""

from __future__ import annotations

from .moves import Pass, PlaceBid
from .state import Bid, GameState


def legal_bids(state: GameState) -> tuple[Bid, ...]:
    """Every bid the player to act may legally make, for client display and validation."""
    raise NotImplementedError("Phase 0: bidding state machine")


def apply_bid(state: GameState, move: PlaceBid | Pass) -> GameState:
    """Validate and apply a bid or pass, advancing the auction.

    Raises :class:`~t42.engine.errors.OutOfTurn` or :class:`~t42.engine.errors.IllegalMove`.
    """
    raise NotImplementedError("Phase 0: bidding state machine")


def auction_is_settled(state: GameState) -> bool:
    """Whether every seat has acted and a declarer can be resolved."""
    raise NotImplementedError("Phase 0: bidding state machine")


def resolve_auction(state: GameState) -> GameState:
    """Close the auction: set declarer, winning bid and contract, move to ``Phase.DECLARING``."""
    raise NotImplementedError("Phase 0: bidding state machine")
