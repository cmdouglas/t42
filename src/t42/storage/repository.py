"""Durable game state in DynamoDB (ROADMAP.md 1.3), per DESIGN.md §4.1's single-table shape:
``META``, ``EVENT#<seq>``, ``STATE`` and ``PLAYER#`` items under one partition per game.

Functions here take a boto3 ``Table`` resource as an explicit parameter rather than owning a
connection themselves - the same injected-dependency style as ``rng: Random`` throughout the
engine, and it keeps this module trivially testable against a moto-backed table.

``TransactWriteItems`` isn't a resource-level method - it's only on the client - but
``table.meta.client`` is still the *resource's* client, carrying the same auto-serialization hooks
as ``Table.put_item``/``get_item``: it accepts plain Python values in ``Item``/``Key``/
``ExpressionAttributeValues`` directly, same as everywhere else in this module. (A client built via
``boto3.client("dynamodb")`` instead of a resource does not carry those hooks and would need
``boto3.dynamodb.types.TypeSerializer`` - the resource's client does the same conversion for us.)
Reads go through the resource's ``get_item``, which auto-deserializes, but always to ``Decimal``
for numbers rather than ``int``; ``_from_dynamo`` converts that back before anything reaches
``codec.decode_game_state``, which was never written to expect ``Decimal`` (deliberately -
``codec.py`` stays boto3-and-repository-agnostic, so this conversion lives here instead).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from random import Random
from typing import Any, cast

from botocore.exceptions import ClientError
from mypy_boto3_dynamodb.service_resource import Table
from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

from t42.engine.events import Event
from t42.engine.game import new_game
from t42.engine.house_rules import HouseRules
from t42.engine.state import GameId, GameState, PlayerId, Seat

from .codec import decode_game_state, encode_event, encode_game_state, encode_house_rules
from .errors import GameAlreadyExists, GameNotFound, VersionConflict
from .events import hand_dealt_event


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _game_pk(game_id: GameId) -> str:
    return f"GAME#{game_id}"


def _player_pk(player_id: PlayerId) -> str:
    return f"PLAYER#{player_id}"


def _game_sk(game_id: GameId) -> str:
    return f"GAME#{game_id}"


def _event_sk(seq: int) -> str:
    return f"EVENT#{seq:06d}"


def _transact_write(table: Table, items: list[dict[str, Any]]) -> None:
    """boto3-stubs types ``TransactItems`` against the raw wire-format ``AttributeValue`` shape,
    unaware that ``table.meta.client`` carries the resource's auto-serialization hooks and accepts
    plain Python values at runtime (see the module docstring) - the ``cast`` reconciles the two."""
    table.meta.client.transact_write_items(
        TransactItems=cast(Sequence[TransactWriteItemTypeDef], items)
    )


def _from_dynamo(value: Any) -> Any:
    """Undoes the resource API's Number -> ``Decimal`` deserialization, recursively. Domino
    scoring never produces a fractional value, so this is always exact."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class StoredGame:
    """What a read returns: the decoded state plus the ``version`` ``append`` must be given back
    to write the next event. ``version`` lives here, not on ``GameState`` - optimistic-concurrency
    bookkeeping is a storage concern, not a rules concern (invariant 1)."""

    state: GameState
    version: int


def create_game(
    table: Table,
    game_id: GameId,
    players: Mapping[Seat, PlayerId],
    config: HouseRules,
    rng: Random,
    *,
    now: Callable[[], datetime] = _utcnow,
) -> GameState:
    """Deals the first hand and persists ``META``, the opening ``HAND_DEALT`` event, ``STATE``
    (``version=1``) and one ``PLAYER#`` item per seat, in a single transaction. Raises
    ``GameAlreadyExists`` if ``game_id`` is already in use."""
    state = new_game(game_id, players, config, rng=rng)
    assert state.hand is not None
    event = hand_dealt_event(state.hand)
    encoded_state = encode_game_state(state)
    timestamp = now().isoformat()

    transact_items: list[dict[str, Any]] = [
        {
            "Put": {
                "TableName": table.name,
                "Item": {
                    "PK": _game_pk(game_id),
                    "SK": "META",
                    "players": encoded_state["players"],
                    "config": encode_house_rules(config),
                    "created_at": timestamp,
                    "last_activity_at": timestamp,
                },
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Put": {
                "TableName": table.name,
                "Item": {
                    "PK": _game_pk(game_id),
                    "SK": _event_sk(0),
                    "seq": 0,
                    "timestamp": timestamp,
                    **encode_event(event),
                },
                "ConditionExpression": "attribute_not_exists(SK)",
            }
        },
        {
            "Put": {
                "TableName": table.name,
                "Item": {
                    "PK": _game_pk(game_id),
                    "SK": "STATE",
                    "version": 1,
                    "state": encoded_state,
                },
                "ConditionExpression": "attribute_not_exists(SK)",
            }
        },
        *(
            {
                "Put": {
                    "TableName": table.name,
                    "Item": {
                        "PK": _player_pk(player_id),
                        "SK": _game_sk(game_id),
                        "seat": seat.value,
                        "is_my_turn": seat == state.to_act,
                    },
                    "ConditionExpression": "attribute_not_exists(SK)",
                }
            }
            for seat, player_id in players.items()
        ),
    ]

    try:
        _transact_write(table, transact_items)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise GameAlreadyExists(game_id) from exc
        raise
    return state


def get_state(table: Table, game_id: GameId) -> StoredGame:
    """Reads the materialized ``STATE`` item. Raises ``GameNotFound`` if none exists."""
    response = table.get_item(Key={"PK": _game_pk(game_id), "SK": "STATE"})
    item = response.get("Item")
    if item is None:
        raise GameNotFound(game_id)
    normalized = _from_dynamo(item)
    return StoredGame(state=decode_game_state(normalized["state"]), version=normalized["version"])


def append(
    table: Table,
    game_id: GameId,
    events: Sequence[Event],
    new_state: GameState,
    expected_version: int,
    *,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    """Writes ``events`` and the resulting ``new_state`` in one transaction, conditioned on
    ``expected_version`` still matching what's stored - the write optimistic concurrency depends
    on. Also updates ``META.last_activity_at`` (DESIGN.md §9) and every ``PLAYER#`` item's turn
    status. Raises ``VersionConflict`` if the transaction is cancelled; returns the new version on
    success."""
    timestamp = now().isoformat()
    new_version = expected_version + len(events)

    transact_items: list[dict[str, Any]] = [
        {
            "Put": {
                "TableName": table.name,
                "Item": {
                    "PK": _game_pk(game_id),
                    "SK": _event_sk(expected_version + i),
                    "seq": expected_version + i,
                    "timestamp": timestamp,
                    **encode_event(event),
                },
                "ConditionExpression": "attribute_not_exists(SK)",
            }
        }
        for i, event in enumerate(events)
    ]
    transact_items.append(
        {
            "Update": {
                "TableName": table.name,
                "Key": {"PK": _game_pk(game_id), "SK": "STATE"},
                "UpdateExpression": "SET #state = :state, #version = :new_version",
                "ConditionExpression": "#version = :expected_version",
                "ExpressionAttributeNames": {"#state": "state", "#version": "version"},
                "ExpressionAttributeValues": {
                    ":state": encode_game_state(new_state),
                    ":new_version": new_version,
                    ":expected_version": expected_version,
                },
            }
        }
    )
    transact_items.append(
        {
            "Update": {
                "TableName": table.name,
                "Key": {"PK": _game_pk(game_id), "SK": "META"},
                "UpdateExpression": "SET last_activity_at = :ts",
                "ExpressionAttributeValues": {":ts": timestamp},
            }
        }
    )
    transact_items.extend(
        {
            "Update": {
                "TableName": table.name,
                "Key": {"PK": _player_pk(player_id), "SK": _game_sk(game_id)},
                "UpdateExpression": "SET is_my_turn = :turn",
                "ExpressionAttributeValues": {":turn": seat == new_state.to_act},
            }
        }
        for seat, player_id in new_state.players.items()
    )

    try:
        _transact_write(table, transact_items)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise VersionConflict(game_id, expected_version) from exc
        raise
    return new_version
