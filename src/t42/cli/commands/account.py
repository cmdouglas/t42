"""``register``, ``login``, ``logout``, ``whoami`` (ROADMAP.md 3.4, DESIGN.md §7).

``register`` and ``login`` both mint a token and save it as a local profile - the only difference
is which endpoint mints it. Neither takes a plaintext password on the command line unless the
caller opts into that with ``--password``; left unset, ``getpass`` prompts instead, so scripts and
tests can still drive these commands non-interactively.
"""

from __future__ import annotations

import argparse
import getpass

from t42.cli import config, render
from t42.cli.command import Command
from t42.cli.context import build_client, emit


def _add_credential_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username")
    parser.add_argument("--password", default=None)


def _read_password(args: argparse.Namespace) -> str:
    if args.password is not None:
        return str(args.password)
    return getpass.getpass("Password: ")


def _save_profile(args: argparse.Namespace, response: dict[str, object]) -> None:
    profile_name = args.profile or "default"
    cfg = config.load()
    cfg = config.set_profile(
        cfg,
        profile_name,
        config.Profile(
            player_id=str(response["player_id"]),
            username=str(response["username"]),
            token=str(response["token"]),
        ),
    )
    config.save(cfg)


def _register(args: argparse.Namespace) -> int:
    client, _ = build_client(args, require_auth=False)
    response = client.request(
        "POST",
        "/players",
        json={"username": args.username, "password": _read_password(args)},
    )
    _save_profile(args, response)
    emit(args, response, render.render_token)
    return 0


def _login(args: argparse.Namespace) -> int:
    client, _ = build_client(args, require_auth=False)
    response = client.request(
        "POST",
        "/sessions",
        json={"username": args.username, "password": _read_password(args)},
    )
    _save_profile(args, response)
    emit(args, response, render.render_token)
    return 0


def _logout(args: argparse.Namespace) -> int:
    client, _ = build_client(args)
    response = client.request("DELETE", "/sessions/current")
    profile_name = args.profile or "default"
    cfg = config.load()
    cfg = config.remove_profile(cfg, profile_name)
    config.save(cfg)
    emit(args, response, confirmation=f"logged out ({profile_name})")
    return 0


def _whoami(args: argparse.Namespace) -> int:
    client, _ = build_client(args)
    response = client.request("GET", "/players/me")
    emit(args, response, render.render_profile)
    return 0


COMMANDS: tuple[Command, ...] = (
    Command(
        name="register",
        help="create an account and sign in",
        configure=_add_credential_args,
        handler=_register,
    ),
    Command(
        name="login", help="sign in on this device", configure=_add_credential_args, handler=_login
    ),
    Command(
        name="logout", help="sign out this device", configure=lambda parser: None, handler=_logout
    ),
    Command(
        name="whoami",
        help="show the signed-in player",
        configure=lambda parser: None,
        handler=_whoami,
    ),
)
