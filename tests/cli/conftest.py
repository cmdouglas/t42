"""Shared fixtures for ``tests/cli/`` (ROADMAP.md 3.7).

``_config_home`` is autouse so no test under here ever touches a real
``~/.config/t42/config.json`` - it's the same one-line isolation every ``test_commands_*.py`` file
already hand-rolled individually; promoted here once ``conftest.py`` existed for
:func:`cli_app_client` anyway.

``cli_app_client`` mirrors ``tests/api/conftest.py``'s ``client`` fixture exactly: the real FastAPI
app in-process, with only the boto3 table swapped for the moto-backed one. It's what
``context.transport_factory`` gets pointed at so `main(argv)` can be driven against the real app
rather than a `FakeTransport` (ROADMAP.md 3.2's whole reason for the `Transport` protocol).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mypy_boto3_dynamodb.service_resource import Table

from t42.api.app import app
from t42.api.deps import get_table


@pytest.fixture(autouse=True)
def _config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def cli_app_client(table: Table) -> Iterator[TestClient]:
    app.dependency_overrides[get_table] = lambda: table
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
