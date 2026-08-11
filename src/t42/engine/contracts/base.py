"""The contract strategy interface (DESIGN.md §5, "Contract strategies").

Everything that differs between standard play, nello, plunge, sevens and splash sits behind this
protocol, so the trick engine and bidding machine never branch on contract name.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import RuleConfig
from ..dominoes import Domino
from ..state import Bid, GameState, Seat, Team, Trick
from ..suits import Trump


@runtime_checkable
class Contract(Protocol):
    """A contract's rules for leading, trump, legal plays and scoring."""

    #: Registry key, and the value stored in events and state.
    name: str

    def validate_bid(self, bid: Bid, config: RuleConfig) -> None:
        """Reject bids this contract cannot be bid at. Raises ``IllegalMove``."""
        ...

    def requires_declaration(self) -> bool:
        """Whether the declarer must declare something (trump, partner sit-out) before play."""
        ...

    def opening_leader(self, state: GameState) -> Seat:
        """Who leads the first trick."""
        ...

    def sits_out(self, state: GameState) -> Seat | None:
        """The seat that sits the hand out, if the contract dictates one (nello)."""
        ...

    def legal_plays(
        self, hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig
    ) -> tuple[Domino, ...]:
        """Legal plays under this contract, tightening or replacing the default follow-suit rule."""
        ...

    def trick_winner(self, trick: Trick, trump: Trump, config: RuleConfig) -> Seat:
        """Winner of a completed trick under this contract (sevens ranks by pip distance from 7)."""
        ...

    def score_hand(self, state: GameState) -> dict[Team, int]:
        """Marks won by each team when the hand ends."""
        ...
