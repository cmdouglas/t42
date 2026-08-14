"""Pure ``dict -> (subject, body)`` renderers, one per notification kind (ROADMAP.md 4.1).

No I/O, no client library: the interesting part of a notification is its content, and content
should be assertable without a transport - the same property ``t42.cli.render`` has for the same
reason. These renderers do not decide who gets notified or when; that is ROADMAP.md 4.5's handler,
which will call the function it needs by name, the same way ``t42.cli``'s command handlers call
``render.render_game`` and friends directly rather than through a dispatch table.

Every dict shares ``game_id`` (game ids double as join codes, DESIGN.md §4.1, so there is no
separate join-code key) and ``recipient_username``. ``render_game_over``'s ``marks`` key has the
same ``{"north_south": int, "east_west": int}`` shape ``t42.engine.projection.project`` already
emits, so a caller can pass ``META``'s stored marks straight through. ``render_invite``'s
``invited_by`` key does not exist in storage yet - ``invite_player`` currently writes only
``{game_id, created_at}`` - 4.5 adds it; this module just assumes it will be present.
"""

from __future__ import annotations

from typing import Any


def render_your_turn(data: dict[str, Any]) -> tuple[str, str]:
    """Expects: game_id, recipient_username."""
    game_id = data["game_id"]
    subject = f"It's your turn in game {game_id}"
    body = f"Hi {data['recipient_username']},\n\nIt's your turn in game {game_id}."
    return subject, body


def render_game_over(data: dict[str, Any]) -> tuple[str, str]:
    """Expects: game_id, recipient_username, marks {"north_south": int, "east_west": int}."""
    game_id = data["game_id"]
    marks = data["marks"]
    subject = f"Game {game_id} is over"
    body = (
        f"Hi {data['recipient_username']},\n\n"
        f"Game {game_id} is over. Final marks: "
        f"North/South {marks['north_south']} - East/West {marks['east_west']}."
    )
    return subject, body


def render_invite(data: dict[str, Any]) -> tuple[str, str]:
    """Expects: game_id, recipient_username, invited_by."""
    subject = "You've been invited to a table"
    body = (
        f"Hi {data['recipient_username']},\n\n"
        f"{data['invited_by']} has invited you to game {data['game_id']}."
    )
    return subject, body
