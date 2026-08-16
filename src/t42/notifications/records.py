"""Decodes raw DynamoDB Streams records into plain data (ROADMAP.md 4.4).

A stream record carries DynamoDB-JSON attribute values (``{"S": "foo"}``, ``{"N": "3"}``, ...) -
the one place in this codebase that shape is visible, since everywhere else goes through the
resource-level ``Table`` API, which hands back plain Python values directly. This module is the
single translation point, so :mod:`t42.notifications.handler` (ROADMAP.md 4.5) can pattern-match
against plain dicts and be tested without a stream, the same way :mod:`t42.storage.codec` and
:mod:`t42.cli.render` each have their own single translation point for their own wire shapes.

Pure, no I/O - this only ever touches the record dict it's handed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

_deserializer = TypeDeserializer()


@dataclass(frozen=True, slots=True)
class Transition:
    """One stream record, decoded. ``keys`` is always present (every event type carries it);
    ``old``/``new`` are ``None`` when the record has no ``OldImage`` (an ``INSERT``) or no
    ``NewImage`` (a ``REMOVE``) - never present in the record at all rather than an empty dict, so
    a rule can tell "no prior value" apart from "prior value happened to be empty"."""

    event_name: str
    keys: dict[str, Any]
    old: dict[str, Any] | None
    new: dict[str, Any] | None


def _decode(image: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _deserializer.deserialize(value) for key, value in image.items()}


def _decode_optional(image: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if image is None else _decode(image)


def transition_from_record(record: Mapping[str, Any]) -> Transition:
    """Decodes one entry of a stream batch's ``Records`` list - the same shape whether it arrived
    via a real Lambda event-source mapping or :mod:`t42.notifications.pump`'s local poll."""
    body = record["dynamodb"]
    return Transition(
        event_name=record["eventName"],
        keys=_decode(body["Keys"]),
        old=_decode_optional(body.get("OldImage")),
        new=_decode_optional(body.get("NewImage")),
    )
