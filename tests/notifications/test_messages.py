"""ROADMAP.md 4.1: the pure ``dict -> (subject, body)`` renderers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from t42.notifications.messages import render_game_over, render_invite, render_your_turn

_CASES: tuple[tuple[Callable[[dict[str, Any]], tuple[str, str]], dict[str, Any]], ...] = (
    (
        render_your_turn,
        {"game_id": "7F3AKM", "recipient_username": "alice"},
    ),
    (
        render_game_over,
        {
            "game_id": "7F3AKM",
            "recipient_username": "alice",
            "marks": {"north_south": 0, "east_west": 0},
        },
    ),
    (
        render_game_over,
        {
            "game_id": "7F3AKM",
            "recipient_username": "alice",
            "marks": {"north_south": 7, "east_west": 3},
        },
    ),
    (
        render_invite,
        {"game_id": "7F3AKM", "recipient_username": "alice", "invited_by": "bob"},
    ),
)


@pytest.mark.parametrize(("renderer", "data"), _CASES)
def test_renderer_returns_nonempty_subject_and_body(
    renderer: Callable[[dict[str, Any]], tuple[str, str]], data: dict[str, Any]
) -> None:
    subject, body = renderer(data)
    assert isinstance(subject, str) and subject
    assert isinstance(body, str) and body


def test_render_your_turn_mentions_game_and_recipient() -> None:
    data = {"game_id": "7F3AKM", "recipient_username": "alice"}
    subject, body = render_your_turn(data)
    assert "7F3AKM" in subject
    assert "7F3AKM" in body
    assert "alice" in body


def test_render_game_over_reports_final_marks() -> None:
    data = {
        "game_id": "7F3AKM",
        "recipient_username": "alice",
        "marks": {"north_south": 7, "east_west": 3},
    }
    subject, body = render_game_over(data)
    assert "7F3AKM" in subject
    assert "7" in body
    assert "3" in body


def test_render_game_over_reports_zero_zero() -> None:
    data = {
        "game_id": "7F3AKM",
        "recipient_username": "alice",
        "marks": {"north_south": 0, "east_west": 0},
    }
    _, body = render_game_over(data)
    assert "North/South 0" in body
    assert "East/West 0" in body


def test_render_invite_mentions_inviter_and_game() -> None:
    data = {"game_id": "7F3AKM", "recipient_username": "alice", "invited_by": "bob"}
    _, body = render_invite(data)
    assert "bob" in body
    assert "7F3AKM" in body
