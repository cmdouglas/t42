"""Shared nello/nello_low mechanics.

Both: declarer's partner sits out (hand played 3-handed), no trump, declarer leads the first
trick, declarer's side makes the bid only by losing every trick. The two contracts differ only in
how a double ranks - each subclass fixes its own ``_doubles_are_own_suit``/``_doubles_rank``,
independent of the game's ``RuleConfig.doubles_are_own_suit`` (DESIGN.md §12).
"""

from __future__ import annotations

from dataclasses import replace

from ..config import RuleConfig
from ..dominoes import Domino
from ..errors import IllegalMove
from ..state import Bid, GameState, Seat, Team, Trick, other_team, partner_of, team_of
from ..suits import DoublesRank, Trump
from ..trick_rules import follow_suit_plays, highest_trump_or_led_suit_wins

_MINIMUM_MARKS = 1


class NelloBase:
    """Not itself registered - ``nello.py`` and ``nello_low.py`` provide the two doubles modes."""

    name: str
    _doubles_are_own_suit: bool
    _doubles_rank: DoublesRank

    def _suit_config(self, config: RuleConfig) -> RuleConfig:
        return replace(config, doubles_are_own_suit=self._doubles_are_own_suit)

    def validate_bid(self, bid: Bid, hand: tuple[Domino, ...], config: RuleConfig) -> None:
        if bid.marks is None or bid.marks < _MINIMUM_MARKS:
            raise IllegalMove(f"{self.name} must be bid at {_MINIMUM_MARKS}+ marks")

    def requires_partner_confirmation(self) -> bool:
        return False

    def requires_declaration(self) -> bool:
        return False

    def declaring_seat(self, state: GameState) -> Seat:
        raise AssertionError(f"{self.name} has no declaration step")

    def opening_leader(self, state: GameState) -> Seat:
        assert state.hand is not None and state.hand.declarer is not None
        return state.hand.declarer

    def sits_out(self, state: GameState) -> Seat | None:
        assert state.hand is not None and state.hand.declarer is not None
        return partner_of(state.hand.declarer)

    def legal_plays(
        self, hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig
    ) -> tuple[Domino, ...]:
        return follow_suit_plays(hand, trick, None, self._suit_config(config))

    def trick_winner(self, trick: Trick, trump: Trump, config: RuleConfig) -> Seat:
        return highest_trump_or_led_suit_wins(
            trick, None, self._suit_config(config), doubles_rank=self._doubles_rank
        )

    def score_hand(self, state: GameState) -> dict[Team, int]:
        hand = state.hand
        assert hand is not None and hand.declarer is not None
        declarer = hand.declarer
        declaring_team = team_of(declarer)
        winning_bid = next(b for b in hand.bids if b.bidder == declarer and not b.is_pass)
        assert winning_bid.marks is not None

        declarer_took_a_trick = any(
            trick.winner is not None and team_of(trick.winner) == declaring_team
            for trick in hand.completed_tricks
        )
        if not declarer_took_a_trick:
            return {declaring_team: winning_bid.marks}
        return {other_team(declaring_team): winning_bid.marks}
