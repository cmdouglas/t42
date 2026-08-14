from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from t42.cli import config, context
from t42.cli.api import ApiError
from t42.cli.command import Command
from t42.cli.commands import account

from ._helpers import fake_transport

_TOKEN_RESPONSE = {"player_id": "p1", "username": "alice", "token": "tok-1"}


def _args(
    tmp_path: Path,
    *,
    username: str = "alice",
    password: str | None = "hunter2",
    profile: str | None = None,
    json: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        username=username,
        password=password,
        profile=profile,
        json=json,
        api_url="http://x",
    )


def _command(name: str) -> Command:
    return next(c for c in account.COMMANDS if c.name == name)


def test_register_saves_profile_named_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = fake_transport(_TOKEN_RESPONSE)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    status = _command("register").handler(_args(tmp_path))

    assert status == 0
    cfg = config.load()
    profile = config.get_profile(cfg, "default")
    assert profile == config.Profile("p1", "alice", "tok-1")


def test_register_saves_profile_under_given_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = fake_transport(_TOKEN_RESPONSE)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    _command("register").handler(_args(tmp_path, profile="north"))

    assert config.get_profile(config.load(), "north") is not None
    assert config.get_profile(config.load(), "default") is None


def test_register_sends_username_and_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = fake_transport(_TOKEN_RESPONSE)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    _command("register").handler(_args(tmp_path))

    call = transport.calls[0]
    assert call.method == "POST"
    assert call.url == "/players"
    assert call.json == {"username": "alice", "password": "hunter2"}


def test_register_prompts_for_password_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = fake_transport(_TOKEN_RESPONSE)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "prompted-pw")

    _command("register").handler(_args(tmp_path, password=None))

    assert transport.calls[0].json["password"] == "prompted-pw"


def test_login_saves_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transport = fake_transport(_TOKEN_RESPONSE)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    status = _command("login").handler(_args(tmp_path))

    assert status == 0
    assert transport.calls[0].method == "POST"
    assert transport.calls[0].url == "/sessions"
    assert config.get_profile(config.load(), "default") == config.Profile("p1", "alice", "tok-1")


def test_whoami_renders_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = config.set_profile(config.Config(), "default", config.Profile("p1", "alice", "tok-1"))
    config.save(cfg)
    body = {
        "player_id": "p1",
        "username": "alice",
        "contacts": [],
        "created_at": "2026-01-01T00:00:00Z",
        "devices": [],
    }
    transport = fake_transport(body)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    status = _command("whoami").handler(
        argparse.Namespace(profile=None, json=False, api_url="http://x")
    )

    assert status == 0
    assert transport.calls[0].method == "GET"
    assert transport.calls[0].url == "/players/me"
    assert "alice" in capsys.readouterr().out


def test_whoami_without_a_profile_exits_via_not_authenticated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context, "transport_factory", lambda url: fake_transport({}))

    with pytest.raises(ApiError) as exc_info:
        _command("whoami").handler(argparse.Namespace(profile=None, json=False, api_url="http://x"))

    assert exc_info.value.code == "NOT_AUTHENTICATED"


def test_logout_removes_only_its_own_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = config.set_profile(config.Config(), "north", config.Profile("p1", "alice", "tok-1"))
    cfg = config.set_profile(cfg, "south", config.Profile("p2", "bob", "tok-2"))
    config.save(cfg)
    transport = fake_transport(None, status_code=204)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    status = _command("logout").handler(
        argparse.Namespace(profile="north", json=False, api_url="http://x")
    )

    assert status == 0
    loaded = config.load()
    assert config.get_profile(loaded, "north") is None
    assert config.get_profile(loaded, "south") is not None


def test_logout_calls_delete_sessions_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = config.set_profile(config.Config(), "default", config.Profile("p1", "alice", "tok-1"))
    config.save(cfg)
    transport = fake_transport(None, status_code=204)
    monkeypatch.setattr(context, "transport_factory", lambda url: transport)

    _command("logout").handler(argparse.Namespace(profile=None, json=False, api_url="http://x"))

    assert transport.calls[0].method == "DELETE"
    assert transport.calls[0].url == "/sessions/current"
    assert transport.calls[0].headers["Authorization"] == "Bearer tok-1"
