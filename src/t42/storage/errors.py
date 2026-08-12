"""Errors raised by the repository (ROADMAP.md 1.3).

Mirrors ``t42.engine.errors``'s style: a base class plus specific subclasses, raised rather than
returned, so callers can catch the one they care about or ``StorageError`` for all of them.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base class for every rejection the repository can produce."""


class GameNotFound(StorageError):
    """No ``STATE`` item exists for this ``game_id``."""

    def __init__(self, game_id: str) -> None:
        super().__init__(f"no game found with id {game_id!r}")
        self.game_id = game_id


class GameAlreadyExists(StorageError):
    """``create_game`` was called with a ``game_id`` that already has a ``META`` item."""

    def __init__(self, game_id: str) -> None:
        super().__init__(f"a game already exists with id {game_id!r}")
        self.game_id = game_id


class VersionConflict(StorageError):
    """``append``'s ``expected_version`` no longer matches the stored ``STATE`` item - another
    write landed first. The API layer (Phase 2) turns this into a 409."""

    def __init__(self, game_id: str, expected_version: int) -> None:
        super().__init__(
            f"game {game_id!r} is no longer at version {expected_version} - retry with the "
            "latest state"
        )
        self.game_id = game_id
        self.expected_version = expected_version
