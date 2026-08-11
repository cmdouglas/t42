"""Phase 0 milestone (ROADMAP.md 0.6): play complete games end to end through apply_move, one per
contract, plus a randomized multi-hand smoke test. Nothing here reaches into engine internals -
every step goes through the public new_game/apply_move/legal_moves entry points, exactly as a
future API handler would call them.
"""

from __future__ import annotations

from collections.abc import Callable
from random import Random

import pytest

from t42.engine.config import RuleConfig
from t42.engine.dominoes import Domino
from t42.engine.game import apply_move, legal_moves, new_game
from t42.engine.moves import ConfirmBid, Move, Pass, PlaceBid
from t42.engine.state import GameState, HandState, Phase, Seat, Team

from ._helpers import PLAYERS, custom_deal, player_of

DOUBLES = tuple(Domino(n, n) for n in range(7))


def _first_option(state: GameState, options: tuple[Move, ...]) -> Move:
    return options[0]


Chooser = Callable[[GameState, tuple[Move, ...]], Move]


def _prefer_contract(contract_name: str) -> Chooser:
    def choose(state: GameState, options: tuple[Move, ...]) -> Move:
        if state.phase is Phase.BIDDING:
            for_target = [
                o for o in options if isinstance(o, PlaceBid) and o.contract == contract_name
            ]
            if for_target:
                return min(for_target, key=lambda o: o.marks or 0)
            confirms = [o for o in options if isinstance(o, ConfirmBid)]
            if confirms:
                return next(o for o in confirms if o.accept)
            passes = [o for o in options if isinstance(o, Pass)]
            if passes:
                return passes[0]
        return options[0]

    return choose


def _drive_to_game_over(
    state: GameState, choose: Chooser, rng: Random, *, max_moves: int = 500
) -> GameState:
    for _ in range(max_moves):
        if state.phase is Phase.GAME_OVER:
            return state
        seat = state.to_act
        assert seat is not None
        options = legal_moves(state, player_of(seat))
        assert options, f"{player_of(seat)} has no legal moves in {state.phase}"
        move = choose(state, options)
        state = apply_move(state, move, rng=rng)
    raise AssertionError(f"game did not reach GAME_OVER within {max_moves} moves")


def _plunge_or_splash_deal(
    doubles_holder: Seat, *, extra_doubles: int = 0
) -> dict[Seat, tuple[Domino, ...]]:
    non_doubles = [Domino(6, 5), Domino(6, 4), Domino(5, 4), Domino(4, 3)]
    hand = DOUBLES[: 4 + extra_doubles] + tuple(non_doubles[: 3 - extra_doubles])
    return custom_deal(**{doubles_holder.name.lower(): hand})


def _run_single_hand_game(
    hands: dict[Seat, tuple[Domino, ...]],
    *,
    dealer: Seat,
    contract_name: str,
    config: RuleConfig | None = None,
) -> GameState:
    state = GameState(
        game_id="full-game",
        config=config or RuleConfig(marks_to_win=1),
        players=dict(PLAYERS),
        phase=Phase.BIDDING,
        marks={Team.NORTH_SOUTH: 0, Team.EAST_WEST: 0},
        hand=HandState(dealer=dealer, hands=hands),
        to_act=Seat((dealer + 1) % 4),
    )
    final = _drive_to_game_over(state, _prefer_contract(contract_name), Random(0))
    assert final.hand is None
    assert final.phase is Phase.GAME_OVER
    return final


def test_full_game_standard() -> None:
    rng = Random(1)
    state = new_game("g-standard", PLAYERS, RuleConfig(marks_to_win=1), rng=rng)
    final = _drive_to_game_over(state, _first_option, rng)
    assert final.phase is Phase.GAME_OVER
    assert final.hand is None
    assert sum(final.marks.values()) >= 1


@pytest.mark.parametrize("contract_name", ["nello", "nello_low", "sevens"])
def test_full_game_no_doubles_requirement_contracts(contract_name: str) -> None:
    rng = Random(2)
    config = RuleConfig(
        enabled_contracts=frozenset({"standard", "nello", "nello_low", "sevens"}),
        marks_to_win=1,
    )
    state = new_game(f"g-{contract_name}", PLAYERS, config, rng=rng)
    final = _drive_to_game_over(state, _prefer_contract(contract_name), rng)
    assert final.phase is Phase.GAME_OVER
    assert final.hand is None
    assert sum(final.marks.values()) >= 1


def test_full_game_plunge() -> None:
    hands = _plunge_or_splash_deal(Seat.NORTH)
    final = _run_single_hand_game(hands, dealer=Seat.WEST, contract_name="plunge")
    assert sum(final.marks.values()) >= 4


def test_full_game_splash() -> None:
    hands = _plunge_or_splash_deal(Seat.NORTH, extra_doubles=1)  # 5 doubles, well above the 3 min
    config = RuleConfig(
        enabled_contracts=frozenset({"standard", "nello", "plunge", "sevens", "splash"}),
        marks_to_win=1,
    )
    final = _run_single_hand_game(hands, dealer=Seat.WEST, contract_name="splash", config=config)
    assert sum(final.marks.values()) >= 2


def test_full_random_game_reaches_game_over_across_several_hands() -> None:
    rng = Random(99)
    state = new_game("g-random", PLAYERS, RuleConfig(), rng=rng)  # default marks_to_win=7

    def choose(state: GameState, options: tuple[Move, ...]) -> Move:
        return rng.choice(options)

    final = _drive_to_game_over(state, choose, rng, max_moves=5000)
    assert final.phase is Phase.GAME_OVER
    assert final.hand is None
    assert any(m >= final.config.marks_to_win for m in final.marks.values())


def test_full_random_games_never_crash_across_many_seeds() -> None:
    for seed in range(25):
        rng = Random(seed)
        state = new_game(f"g-{seed}", PLAYERS, RuleConfig(marks_to_win=2), rng=rng)

        def choose(state: GameState, options: tuple[Move, ...], rng: Random = rng) -> Move:
            return rng.choice(options)

        final = _drive_to_game_over(state, choose, rng, max_moves=2000)
        assert final.phase is Phase.GAME_OVER
