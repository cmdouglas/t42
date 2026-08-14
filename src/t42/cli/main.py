"""Argument parsing and command dispatch (ROADMAP.md 3.1).

``main`` returns an exit code for every expected failure rather than raising or calling
``sys.exit`` itself, so a command stays a plain function a test can call - the process boundary
(the ``t42`` console script installed by ``pyproject.toml``) carries no logic beyond
``sys.exit(main())``.

Global flags (``--api-url``, ``--profile``, ``--json``) are declared once, on the top-level parser
only, and so must precede the subcommand (``t42 --profile north status ABC``, not the reverse).
``argparse`` subparsers parse into a fresh sub-namespace and merge it onto the outer one, defaults
included - declaring the same flags on every subparser so they could also appear after the
subcommand would let an unset subparser default silently clobber a value already given before it.
One declaration site avoids that.

``_COMMANDS`` is empty in this phase: no command exists yet that doesn't need the HTTP client
ROADMAP.md 3.2 builds next. It is the table ROADMAP.md 3.4 and 3.5 append real commands to.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NoReturn

from t42.cli import config


class _ExitSignal(Exception):
    """Raised in place of ``SystemExit`` so ``main`` can turn it back into a return value."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _ArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            self._print_message(message, sys.stderr)
        raise _ExitSignal(status)


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    help: str
    configure: Callable[[argparse.ArgumentParser], None]
    handler: Callable[[argparse.Namespace], int]


_COMMANDS: tuple[Command, ...] = ()


def build_parser(commands: Sequence[Command] = _COMMANDS) -> _ArgumentParser:
    parser = _ArgumentParser(prog="t42")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("T42_API_URL", config.DEFAULT_API_URL),
    )
    parser.add_argument("--profile", default=os.environ.get("T42_PROFILE"))
    parser.add_argument("--json", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    for command in commands:
        sub = subparsers.add_parser(command.name, help=command.help)
        command.configure(sub)

    return parser


def _run(argv: list[str] | None, commands: Sequence[Command]) -> int:
    parser = build_parser(commands)
    try:
        args = parser.parse_args(argv)
    except _ExitSignal as exc:
        return exc.status

    by_name = {command.name: command for command in commands}
    return by_name[args.command].handler(args)


def main(argv: list[str] | None = None) -> int:
    return _run(argv, _COMMANDS)


if __name__ == "__main__":
    sys.exit(main())
