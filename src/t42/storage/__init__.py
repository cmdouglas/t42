"""DynamoDB event log + materialized state (DESIGN.md §4.1, Phase 1).

``codec`` is the only piece implemented so far: it translates engine dataclasses to and from the
plain attribute maps the storage layer persists. The repository (writes, replay, idempotency) and
the player-specific projection land in later Phase 1 steps - see ROADMAP.md.
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

__all__ = [
    "decode_event",
    "decode_game_state",
    "decode_house_rules",
    "encode_event",
    "encode_game_state",
    "encode_house_rules",
]
