# Texas 42 Online

A server-authoritative, asynchronous implementation of [Texas 42](https://en.wikipedia.org/wiki/42_(dominoes)):
partnership domino trick-taking with nello, plunge and sevens. See [DESIGN.md](DESIGN.md) for the
full design and phase plan.

## Status

Phase 0 (pure rules engine) is in progress. Implemented: tile representation and notation, suit /
trump logic including the doubles-as-own-suit variant, count values, rule config, and the contract
registry. Not yet implemented: the bidding state machine, the five contract strategies, trick
resolution, and the player-projected view. Each is a stub with its signature in place.

## Layout

```
src/t42/engine/     pure rules library: no I/O, no AWS, no dependency on the layers below
src/t42/storage/    DynamoDB event log + materialized state   (Phase 1)
src/t42/api/        Lambda handlers behind API Gateway        (Phase 2)
src/t42/cli/        thin command-line client                  (Phase 3)
tests/engine/
```

The engine is the only place game rules live; every client type consumes the same projected view,
so hidden-information rules exist in exactly one place.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 matches the AWS Lambda runtime targeted in
Phase 2 and is fetched automatically.

```bash
uv sync --extra dev     # create the venv and install dev tooling
uv run pytest           # tests
uv run mypy             # type check (strict)
uv run ruff check .     # lint
uv run ruff format .    # format
```
