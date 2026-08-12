"""DynamoDB event log + materialized state (DESIGN.md §4.1, Phase 1).

``codec`` translates engine dataclasses to and from the plain attribute maps the storage layer
persists. ``events`` translates an accepted move (and the deal it may trigger) into the event
that gets appended to the log. ``replay`` rebuilds a ``GameState`` from that log. ``repository``
writes games to DynamoDB - ``create_game``, ``get_state`` and ``append`` - with optimistic
concurrency via ``STATE.version``. Idempotency and the player-specific projection land in later
Phase 1 steps - see ROADMAP.md.
"""

from __future__ import annotations

from .codec import (
    decode_event,
    decode_game_state,
    decode_house_rules,
    encode_event,
    encode_game_state,
    encode_house_rules,
)
from .errors import GameAlreadyExists, GameNotFound, StorageError, VersionConflict
from .events import event_for_move, events_for_move, hand_dealt_event
from .replay import replay
from .repository import StoredGame, append, create_game, get_state

__all__ = [
    "GameAlreadyExists",
    "GameNotFound",
    "StorageError",
    "StoredGame",
    "VersionConflict",
    "append",
    "create_game",
    "decode_event",
    "decode_game_state",
    "decode_house_rules",
    "encode_event",
    "encode_game_state",
    "encode_house_rules",
    "event_for_move",
    "events_for_move",
    "get_state",
    "hand_dealt_event",
    "replay",
]
