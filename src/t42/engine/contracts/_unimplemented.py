"""Shared placeholder base for contract strategies awaiting Phase 0 implementation.

Each strategy drops this base as it is implemented; when the last one does, this module goes away.
"""

from __future__ import annotations

from ..config import RuleConfig
from ..dominoes import Domino
from ..state import Bid, GameState, Seat, Team, Trick
from ..suits import Trump


class UnimplementedContract:
    """Satisfies :class:`~t42.engine.contracts.base.Contract`; every method raises."""

    name: str = ""

    def _todo(self) -> NotImplementedError:
        return NotImplementedError(f"Phase 0: {self.name} contract")

    def validate_bid(self, bid: Bid, config: RuleConfig) -> None:
        raise self._todo()

    def requires_declaration(self) -> bool:
        raise self._todo()

    def opening_leader(self, state: GameState) -> Seat:
        raise self._todo()

    def sits_out(self, state: GameState) -> Seat | None:
        raise self._todo()

    def legal_plays(
        self, hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig
    ) -> tuple[Domino, ...]:
        raise self._todo()

    def trick_winner(self, trick: Trick, trump: Trump, config: RuleConfig) -> Seat:
        raise self._todo()

    def score_hand(self, state: GameState) -> dict[Team, int]:
        raise self._todo()
