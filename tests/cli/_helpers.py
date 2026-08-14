"""Shared test doubles for ``tests/cli/`` (ROADMAP.md 3.4), mirroring the ``tests/storage/`` /
``tests/api/`` convention of a per-package ``_helpers.py``.

``FakeTransport`` implements ``t42.cli.api.Transport`` without any network, and records every
call so a test can assert on method/path/body/headers - the same pair ``test_api.py`` already
defines privately; this is the promoted, reusable version.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FakeResponse:
    status_code: int
    body: Any = None

    def json(self) -> Any:
        if self.body is None:
            raise ValueError("no body")
        return self.body


@dataclass(slots=True)
class FakeCall:
    method: str
    url: str
    json: Any
    headers: Mapping[str, str]


@dataclass(slots=True)
class FakeTransport:
    """Returns ``responses`` in order, one per call; the last one repeats once exhausted."""

    responses: list[FakeResponse]
    calls: list[FakeCall] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(FakeCall(method, url, json, headers or {}))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def fake_transport(*bodies: Any, status_code: int = 200) -> FakeTransport:
    """One 200 response per body, in order - the common case for tests that don't care about
    varying the status code."""
    return FakeTransport([FakeResponse(status_code, body) for body in bodies])
