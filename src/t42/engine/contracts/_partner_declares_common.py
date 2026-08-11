"""Shared plunge/splash mechanics: the bidder's partner (not the bidder) names trump and leads
the first trick, after the bidder shows enough doubles to support a mostly-doubles hand. Trick
play proceeds exactly like standard once trump is set. The declaring side must take every point
(all 42) to make the bid - anything less means the bid is set. The two contracts differ only in
their doubles/marks minimum and whether the bid needs the partner's confirmation (plunge only) -
see DESIGN.md §12.
"""

from __future__ import annotations

from ..config import RuleConfig
from ..dominoes import Domino
from ..errors import IllegalMove
from ..scoring import MAX_HAND_POINTS, POINT_PER_TRICK, count_of
from ..state import Bid, GameState, Seat, Team, Trick, other_team, partner_of, team_of
from ..suits import Trump
from ..trick_rules import follow_suit_plays, highest_trump_or_led_suit_wins


class PartnerDeclaresBase:
    """Not itself registered - ``plunge.py`` and ``splash.py`` set the minimums and confirmation
    requirement."""

    name: str
    _minimum_doubles: int
    _minimum_marks: int
    _requires_confirmation: bool

    def validate_bid(self, bid: Bid, hand: tuple[Domino, ...], config: RuleConfig) -> None:
        if bid.marks is None or bid.marks < self._minimum_marks:
            raise IllegalMove(f"{self.name} must be bid at {self._minimum_marks}+ marks")
        doubles_held = sum(1 for domino in hand if domino.is_double)
        if doubles_held < self._minimum_doubles:
            raise IllegalMove(
                f"{self.name} requires holding at least {self._minimum_doubles} doubles, "
                f"got {doubles_held}"
            )

    def requires_partner_confirmation(self) -> bool:
        return self._requires_confirmation

    def requires_declaration(self) -> bool:
        return True

    def declaring_seat(self, state: GameState) -> Seat:
        assert state.hand is not None and state.hand.declarer is not None
        return partner_of(state.hand.declarer)

    def opening_leader(self, state: GameState) -> Seat:
        assert state.hand is not None and state.hand.declarer is not None
        return partner_of(state.hand.declarer)

    def sits_out(self, state: GameState) -> Seat | None:
        return None

    def legal_plays(
        self, hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig
    ) -> tuple[Domino, ...]:
        return follow_suit_plays(hand, trick, trump, config)

    def trick_winner(self, trick: Trick, trump: Trump, config: RuleConfig) -> Seat:
        return highest_trump_or_led_suit_wins(trick, trump, config)

    def score_hand(self, state: GameState) -> dict[Team, int]:
        hand = state.hand
        assert hand is not None and hand.declarer is not None
        declarer = hand.declarer
        declaring_team = team_of(declarer)
        winning_bid = next(b for b in hand.bids if b.bidder == declarer and not b.is_pass)
        assert winning_bid.marks is not None

        declarer_points = sum(
            count_of(tuple(play.domino for play in trick.plays)) + POINT_PER_TRICK
            for trick in hand.completed_tricks
            if trick.winner is not None and team_of(trick.winner) == declaring_team
        )
        if declarer_points == MAX_HAND_POINTS:
            return {declaring_team: winning_bid.marks}
        return {other_team(declaring_team): winning_bid.marks}
