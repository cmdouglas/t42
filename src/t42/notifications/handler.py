"""The notification Lambda entry point (ROADMAP.md 4.5, DESIGN.md §8). Stub.

:mod:`t42.notifications.pump` (ROADMAP.md 4.4) already calls this with a real, Lambda-shaped
batch - the polling and decoding plumbing is finished ahead of the decision logic that consumes
it, the same ordering :mod:`t42.notifications.messages` was built in for 4.1. A stub rather than
nothing to import, per this project's convention: it raises rather than silently doing nothing, so
a green test suite never hides an unfinished phase.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any = None) -> None:
    raise NotImplementedError("Phase 4.5: the notification handler")
