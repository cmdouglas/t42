# CLAUDE.md

Guidance for working in this repository.

## What this is

Texas 42 online: a server-authoritative, asynchronous implementation of the partnership domino
game, including the nello, plunge and sevens special contracts. Games are played over minutes or
hours, not in real time. The MVP ships a CLI client, but the architecture exists so that a web,
mobile or chatbot client is later a thin client against the same API, not a rewrite.

Design priorities, in order: correctness of rules, no leakage of hidden information (hands, undealt
tiles) to the wrong player, and support for long-running asynchronous play. Real-time performance
is not a concern.

- [DESIGN.md](DESIGN.md): architecture and data model. The authority on intent.
- [ROADMAP.md](ROADMAP.md): phase-by-phase execution breakdown and exit criteria.

## Current status

Phase 0 (pure rules engine) is in progress. Implemented and tested: tile representation and
notation, suit and trump logic including the doubles-as-own-suit variant, count values,
`RuleConfig`, and the contract registry. Stubbed with signatures in place and raising
`NotImplementedError`: the bidding state machine, trick engine, all five contract strategies,
projection, and the `game.py` entry points. Nothing under `storage/`, `api/` or `cli/` exists yet.

## Layout

```
src/t42/engine/     pure rules library (Phase 0)
    dominoes.py     the 28 tiles, a-b notation                       IMPLEMENTED
    suits.py        trump membership, led suit, follow, ranking      IMPLEMENTED
    scoring.py      count-domino values, hand point totals           IMPLEMENTED
    config.py       per-game RuleConfig (rule variants)              IMPLEMENTED
    contracts/      Contract protocol + name-keyed registry          registry IMPLEMENTED,
                                                                     strategies stubbed
    state.py        frozen dataclasses: GameState, HandState, Trick
    events.py       immutable log events (the persistence contract)
    moves.py        what a client may propose
    bidding.py      auction state machine                            stub
    tricks.py       trick legality and resolution                    stub
    projection.py   player-specific view                             stub
    game.py         new_game / apply_move / legal_moves entry points stub
    errors.py       RulesError, IllegalMove, OutOfTurn, UnknownContract
src/t42/storage/    DynamoDB event log + materialized state   (Phase 1, not created)
src/t42/api/        Lambda handlers behind API Gateway        (Phase 2, not created)
src/t42/cli/        thin command-line client                  (Phase 3, not created)
tests/engine/       mirrors the engine modules
```

## Commands

Requires [uv](https://docs.astral.sh/uv/); Python 3.13 is fetched automatically.

```bash
uv sync --extra dev     # venv + dev tooling
uv run pytest           # tests
uv run mypy             # strict type check over src and tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

Run all four before considering a change done; CI runs the same set.

## Invariants

These are the rules that keep the design working. Breaking one is a design change, not a detail.

1. **The engine is pure.** Nothing under `t42.engine` may do I/O, import boto3, or import from
   `t42.storage`, `t42.api` or `t42.cli`. It takes a state plus a proposed move and returns a new
   state or raises. Randomness is injected (`rng: Random`), never ambient.
2. **State is immutable.** State types are frozen dataclasses and functions return new state.
   Never mutate in place, so replay, caching and comparison stay sound.
3. **Rule variants are per-game data, never globals.** Anything that differs between rule sets
   lives on `RuleConfig` and is threaded through as an argument. Two games under different variants
   must score and replay correctly in the same process.
4. **Contracts are registered, not switched on.** Behaviour that differs between standard, nello,
   plunge, sevens and splash goes behind the `Contract` protocol in `contracts/`. Do not add
   `if contract == "nello"` branches to the bidding or trick code.
5. **Hidden information has exactly one gate.** `projection.project()` is the only thing that
   decides what a player may see. No handler or client may hand out anything else.
6. **Events are the persistence contract.** The dataclasses in `events.py` are what gets written to
   DynamoDB. Changing a field is a data migration, so treat their shape as an interface.

## Conventions

- Line length 100, ruff lint rules per `pyproject.toml`, mypy `strict` over both `src` and `tests`.
- Prefer frozen slotted dataclasses and plain functions over classes with behaviour, except for
  the contract strategies, where the protocol is the point.
- Tests are table-driven or property-based where the input space is enumerable; the engine gets the
  heaviest test investment, since this is where domino implementations go subtly wrong.
- Stubs raise `NotImplementedError("Phase N: <what>")` and have no tests written against them, so a
  green suite always means what it says.
- Do not pre-decide the rule variants that DESIGN.md §12 leaves open (plunge and sevens scoring,
  nello doubles handling, all-pass behaviour). Settle them there first, then implement.
