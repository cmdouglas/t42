"""Trick play and resolution (DESIGN.md §5).

Legality and the winner are both delegated to the active :class:`~t42.engine.contracts.Contract`
rather than branched on here - see ``legal_plays``/``trick_winner``. What is genuinely generic to
every contract is turn order and when a trick/hand closes, which is what ``play`` owns; it counts
against the *active* seat count (:meth:`Contract.sits_out`), not a hardcoded four, since nello
plays a hand 3-handed.
"""

from __future__ import annotations

from dataclasses import replace

from .config import RuleConfig
from .contracts import Contract
from .contracts import get as get_contract
from .dominoes import Domino
from .errors import IllegalMove, OutOfTurn
from .moves import PlayDomino
from .scoring import TRICKS_PER_HAND
from .state import GameState, Phase, PlayedDomino, Seat, Trick, seat_of
from .suits import Trump


def legal_plays(
    hand: tuple[Domino, ...], trick: Trick, trump: Trump, config: RuleConfig, contract: Contract
) -> tuple[Domino, ...]:
    """The tiles in ``hand`` that may legally be played to ``trick`` under ``contract``.

    Leading, that is the whole hand; following, it is the tiles in the led suit if any are held -
    tightened further only if the contract chooses to (none of the six built-in contracts do).
    """
    return contract.legal_plays(hand, trick, trump, config)


def trick_winner(trick: Trick, trump: Trump, config: RuleConfig, contract: Contract) -> Seat:
    """The seat that wins a completed trick under ``contract``."""
    return contract.trick_winner(trick, trump, config)


def play(state: GameState, move: PlayDomino) -> GameState:
    """Validate and apply a domino play, closing the trick and the hand when they complete."""
    hand = state.hand
    assert hand is not None and hand.contract is not None and state.to_act is not None
    contract = get_contract(hand.contract)

    actor_seat = seat_of(state, move.actor)
    if actor_seat != state.to_act:
        raise OutOfTurn(f"{move.actor} is not the seat to act")

    seat_hand = hand.hands[actor_seat]
    if move.domino not in seat_hand:
        raise IllegalMove(f"{move.actor} does not hold {move.domino}")

    playable = legal_plays(seat_hand, hand.current_trick, hand.trump, state.config, contract)
    if move.domino not in playable:
        raise IllegalMove(f"{move.domino} does not follow suit")

    new_hands = dict(hand.hands)
    new_hands[actor_seat] = tuple(d for d in seat_hand if d != move.domino)
    new_plays = (*hand.current_trick.plays, PlayedDomino(seat=actor_seat, domino=move.domino))

    active = _active_seats(state, contract)
    if len(new_plays) < len(active):
        new_hand = replace(
            hand, hands=new_hands, current_trick=replace(hand.current_trick, plays=new_plays)
        )
        return replace(state, hand=new_hand, to_act=_next_active_seat(actor_seat, active))

    winner = trick_winner(Trick(plays=new_plays), hand.trump, state.config, contract)
    completed_trick = Trick(plays=new_plays, winner=winner)
    new_completed = (*hand.completed_tricks, completed_trick)

    if len(new_completed) == TRICKS_PER_HAND:
        new_hand = replace(
            hand, hands=new_hands, completed_tricks=new_completed, current_trick=Trick()
        )
        return replace(state, hand=new_hand, phase=Phase.HAND_COMPLETE, to_act=None)

    new_hand = replace(hand, hands=new_hands, completed_tricks=new_completed, current_trick=Trick())
    return replace(state, hand=new_hand, to_act=winner)


def _active_seats(state: GameState, contract: Contract) -> tuple[Seat, ...]:
    sitting_out = contract.sits_out(state)
    return tuple(seat for seat in Seat if seat != sitting_out)


def _next_active_seat(current: Seat, active: tuple[Seat, ...]) -> Seat:
    for offset in range(1, len(Seat) + 1):
        candidate = Seat((current + offset) % len(Seat))
        if candidate in active:
            return candidate
    raise AssertionError(f"no active seat after {current} among {active}")
