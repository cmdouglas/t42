"""Shared scaffolding for scripting games directly, bypassing new_game's shuffle so tests control
exactly which dominoes each seat holds. Not collected as a test module (no test_ prefix)."""

from __future__ import annotations

from random import Random

from t42.engine.dominoes import FULL_SET, Domino
from t42.engine.house_rules import HouseRules
from t42.engine.state import GameState, HandState, Phase, PlayerId, Seat, Team

PLAYERS: dict[Seat, PlayerId] = {
    Seat.NORTH: "north",
    Seat.EAST: "east",
    Seat.SOUTH: "south",
    Seat.WEST: "west",
}


def deal(seed: int) -> dict[Seat, tuple[Domino, ...]]:
    """A reproducible 7-each deal, for tests where the exact tiles don't matter."""
    tiles = list(FULL_SET)
    Random(seed).shuffle(tiles)
    return {seat: tuple(tiles[i * 7 : (i + 1) * 7]) for i, seat in enumerate(Seat)}


def make_game(
    hands: dict[Seat, tuple[Domino, ...]],
    *,
    dealer: Seat = Seat.NORTH,
    config: HouseRules | None = None,
    to_act: Seat | None = None,
    marks: dict[Team, int] | None = None,
) -> GameState:
    """A game sitting in Phase.BIDDING with a pre-set deal, ready to script an auction onto."""
    hand = HandState(dealer=dealer, hands=hands)
    return GameState(
        game_id="test-game",
        config=config or HouseRules(),
        players=dict(PLAYERS),
        phase=Phase.BIDDING,
        marks=marks or {Team.NORTH_SOUTH: 0, Team.EAST_WEST: 0},
        hand=hand,
        to_act=to_act if to_act is not None else Seat((dealer + 1) % 4),
    )


def player_of(seat: Seat) -> PlayerId:
    return PLAYERS[seat]


def custom_deal(**explicit_by_seat_name: tuple[Domino, ...]) -> dict[Seat, tuple[Domino, ...]]:
    """A valid deal with some seats pinned to specific tiles and the rest filled from whatever's
    left, in FULL_SET order. Seat names are lowercase: north=(...), east=(...), etc."""
    explicit = {Seat[name.upper()]: tiles for name, tiles in explicit_by_seat_name.items()}
    used = {domino for tiles in explicit.values() for domino in tiles}
    leftover = [domino for domino in FULL_SET if domino not in used]
    hands: dict[Seat, tuple[Domino, ...]] = {}
    for seat in Seat:
        if seat in explicit:
            hands[seat] = explicit[seat]
        else:
            hands[seat] = tuple(leftover[:7])
            leftover = leftover[7:]
    return hands
