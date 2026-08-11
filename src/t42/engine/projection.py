"""Player-specific views (DESIGN.md §4.2). Phase 1, not yet implemented.

The one place hidden-information rules live: every client type consumes this output, so it must
strip other players' hands and the boneyard, and must stay plain JSON-able data with nothing
CLI-specific in it (DESIGN.md §11).
"""

from __future__ import annotations

from typing import Any

from .state import GameState, PlayerId


def project(state: GameState, player_id: PlayerId) -> dict[str, Any]:
    """Render ``state`` as the view ``player_id`` is allowed to see.

    Includes their own hand, the current trick, trump, scores, whose turn it is, and their legal
    moves when it is their turn.
    """
    raise NotImplementedError("Phase 1: player-specific view")
