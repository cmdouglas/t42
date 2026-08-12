"""Repository writes and reads against a moto-backed DynamoDB table (ROADMAP.md 1.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from random import Random

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from t42.engine.events import Event
from t42.engine.game import apply_move, legal_moves
from t42.engine.house_rules import HouseRules
from t42.engine.moves import Move
from t42.engine.state import GameState
from t42.storage.errors import GameAlreadyExists, GameNotFound, VersionConflict
from t42.storage.events import events_for_move, hand_dealt_event
from t42.storage.replay import replay
from t42.storage.repository import append, create_game, get_state

from ..engine._helpers import PLAYERS, drive_to_game_over, prefer_contract


def _create(
    table: Table, game_id: str, *, seed: int = 0, config: HouseRules | None = None
) -> GameState:
    return create_game(table, game_id, PLAYERS, config or HouseRules(), Random(seed))


def test_create_game_round_trips_through_get_state(table: Table) -> None:
    state = _create(table, "g1")

    stored = get_state(table, "g1")

    assert stored.state == state
    assert stored.version == 1


def test_create_game_rejects_a_duplicate_game_id(table: Table) -> None:
    _create(table, "g1")
    with pytest.raises(GameAlreadyExists):
        _create(table, "g1")


def test_get_state_rejects_an_unknown_game_id(table: Table) -> None:
    with pytest.raises(GameNotFound):
        get_state(table, "does-not-exist")


def test_append_an_ordinary_move_advances_version_by_one(table: Table) -> None:
    state = _create(table, "g1")
    seat = state.to_act
    assert seat is not None
    move = legal_moves(state, PLAYERS[seat])[0]
    new_state = apply_move(state, move, rng=Random(1))
    events = events_for_move(state, move, new_state)
    assert len(events) == 1

    new_version = append(table, "g1", events, new_state, expected_version=1)

    assert new_version == 2
    stored = get_state(table, "g1")
    assert stored.version == 2
    assert stored.state == new_state


def test_append_rejects_a_stale_expected_version(table: Table) -> None:
    state = _create(table, "g1")
    stored = get_state(table, "g1")
    seat = state.to_act
    assert seat is not None
    move = legal_moves(state, PLAYERS[seat])[0]
    new_state = apply_move(state, move, rng=Random(2))
    events = events_for_move(state, move, new_state)

    append(table, "g1", events, new_state, stored.version)

    with pytest.raises(VersionConflict):
        append(table, "g1", events, new_state, stored.version)

    assert get_state(table, "g1").version == 2


def test_append_updates_player_turn_status(table: Table) -> None:
    state = _create(table, "g1")
    seat = state.to_act
    assert seat is not None
    move = legal_moves(state, PLAYERS[seat])[0]
    new_state = apply_move(state, move, rng=Random(1))
    events = events_for_move(state, move, new_state)

    append(table, "g1", events, new_state, expected_version=1)

    next_seat = new_state.to_act
    assert next_seat is not None
    for seat_iter, player_id in PLAYERS.items():
        item = table.get_item(Key={"PK": f"PLAYER#{player_id}", "SK": "GAME#g1"})["Item"]
        assert item["is_my_turn"] == (seat_iter == next_seat)


def test_last_activity_at_advances_on_append(table: Table) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)

    state = create_game(table, "g1", PLAYERS, HouseRules(), Random(0), now=lambda: created_at)
    seat = state.to_act
    assert seat is not None
    move = legal_moves(state, PLAYERS[seat])[0]
    new_state = apply_move(state, move, rng=Random(1))
    events = events_for_move(state, move, new_state)

    append(table, "g1", events, new_state, expected_version=1, now=lambda: later)

    meta = table.get_item(Key={"PK": "GAME#g1", "SK": "META"})["Item"]
    assert meta["created_at"] == created_at.isoformat()
    assert meta["last_activity_at"] == later.isoformat()


def test_full_game_through_repository_reaches_game_over_and_matches_replay(table: Table) -> None:
    config = HouseRules()  # default marks_to_win=7: several hands, several re-deals
    game_id = "full-game"
    rng = Random(7)

    state = create_game(table, game_id, PLAYERS, config, rng)
    assert state.hand is not None
    logged_events: list[Event] = [hand_dealt_event(state.hand)]
    version_deltas: list[int] = []

    def record(before: GameState, move: Move, after: GameState) -> None:
        events = events_for_move(before, move, after)
        logged_events.extend(events)
        stored = get_state(table, game_id)
        new_version = append(table, game_id, events, after, stored.version)
        version_deltas.append(new_version - stored.version)

    final = drive_to_game_over(
        state, prefer_contract("standard"), rng, max_moves=5000, on_transition=record
    )

    assert 2 in version_deltas, "expected at least one hand to close and re-deal mid-game"
    stored = get_state(table, game_id)
    assert stored.state == final

    assert replay(game_id, PLAYERS, config, logged_events) == final
