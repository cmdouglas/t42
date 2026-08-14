"""The send channel for player notifications (DESIGN.md §8, ROADMAP.md Phase 4).

``t42.notifications`` may import ``t42.storage.accounts`` and ``boto3``; nothing else from
``t42.storage``, and nothing from ``t42.engine``. That is what makes "the notifier cannot see a
hand" checkable rather than merely claimed: ``repository``, ``codec`` and ``replay`` are the only
path to ``STATE`` or a ``GameState``, and this package never imports them (enforced by
ROADMAP.md 4.7).

``sender`` is the transport - an ``EmailSender`` protocol with a console and an SES
implementation, chosen by environment variable. ``messages`` is pure content - a
``dict -> (subject, body)`` renderer per notification kind. Nothing in this package yet decides
*who* to notify or *when*; that is ROADMAP.md 4.5's handler, built on top of both.
"""

from __future__ import annotations

from .messages import render_game_over, render_invite, render_your_turn
from .sender import (
    EMAIL_SENDER_ENV,
    SES_FROM_ADDRESS_ENV,
    ConsoleSender,
    EmailSender,
    SesSender,
    get_sender,
)

__all__ = [
    "EMAIL_SENDER_ENV",
    "SES_FROM_ADDRESS_ENV",
    "ConsoleSender",
    "EmailSender",
    "SesSender",
    "get_sender",
    "render_game_over",
    "render_invite",
    "render_your_turn",
]
