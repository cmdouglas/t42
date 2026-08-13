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

Phase 0 (pure rules engine) is complete: dealing, bidding (including the plunge confirmation
sub-flow and the dealer-must-bid all-pass rule), all six contracts (standard, nello, nello_low,
sevens, plunge, splash), the trick engine, and a full in-memory game per contract, all through the
public `new_game`/`apply_move`/`legal_moves` entry points. See ROADMAP.md for the exit-criteria
checklist. Nothing under `api/` or `cli/` exists yet.

Phase 0.5 (house rules) is complete. The rule-config type is `HouseRules` in `house_rules.py`;
each contract declares its own options through `option_defaults()`/`validate_options()` (the
plunge/splash doubles-and-marks minimums and the nello/nello_low/sevens mark floor all live in
`contract_options`, not as class attributes); `new_game` rejects an invalid house-rule set via
`contracts.validate_house_rules` before a game is ever created; and declared leads
(`allow_declared_lead`: `never`/`first_trick`/`always`, DESIGN.md §5.2) let a leader name which end
of a two-ended tile is the suit led, recorded on `Trick.declared_suit` and read through
`trick_rules.suit_led` rather than derived.

Phase 1 (persistence) is under way. boto3 landed in 1.3 - see below.

1.1 (item shapes and codec) is complete: `t42.storage.codec` encodes and decodes `GameState`,
`HouseRules` and every `Event` to the plain dict/list/str/int/bool/None shapes boto3's
resource-level `Table` API accepts directly, proven by a round-trip property test in
`tests/storage/` that drives real games through `new_game`/`apply_move` and asserts
`decode(encode(x)) == x` on every intermediate state.

1.2 (replay) is complete. `apply_move` still doesn't emit events itself (unchanged, and still
deliberately out of scope - see 1.1's note above, now resolved by construction rather than
wired-in), so `t42.storage.events` supplies the write direction: `event_for_move`/
`hand_dealt_event`/`events_for_move` translate an accepted move (and any deal it triggers) into
the `Event`(s) it produces. `t42.storage.replay.replay(game_id, players, config, events)` is the
read direction, rebuilding a `GameState` by feeding events back through real `new_game`/
`apply_move` calls - not a parallel reimplementation - using `_ReplayRandom`, a `Random` subclass
whose `shuffle` deterministically replays each `HandDealt` event's recorded deal instead of
randomizing, so dealing runs through its real code path even though the outcome is fixed by
history. Proven against real games (all six contracts, plunge confirmation, declared leads, and a
multi-hand random smoke test) in `tests/storage/test_replay.py`.

1.3 (repository writes) is complete: `t42.storage.repository` is the first real boto3 dependency.
`create_game` deals the first hand and writes `META`, the opening `HAND_DEALT` event, `STATE`
(`version=1`) and one `PLAYER#` item per seat in a single `TransactWriteItems` call; `get_state`
reads the materialized `STATE` item back into a `StoredGame(state, version)`; `append(table,
game_id, events, new_state, expected_version)` writes further events and the resulting state in
one transaction, conditioned on `expected_version` still matching what's stored, and also updates
`META.last_activity_at` and every `PLAYER#` item's turn status. A stale `expected_version` raises
`VersionConflict` (`t42.storage.errors`, alongside `GameNotFound`/`GameAlreadyExists`) - the
optimistic-concurrency guarantee 1.6 will exercise concurrently. `version` lives only in
`StoredGame`, never on `GameState` itself (invariant 1). Tested against `moto`'s in-memory
DynamoDB (`tests/storage/conftest.py`'s `table` fixture) rather than DynamoDB Local, which stays
reserved for 1.6's integration tests per ROADMAP.md; one test drives a full game through
`create_game`/`append` and confirms `t42.storage.replay.replay` over the resulting event log
reproduces the same `STATE` item, tying 1.2 and 1.3 together.

1.4 (idempotency) is complete: `append` takes an optional keyword-only `request_id`; when given, the
same transaction that writes the events and updates `STATE`/`META`/`PLAYER#` also `Put`s a
`REQUEST#<requestId>` marker recording the resulting version, conditioned on its own absence. A
duplicate call with the same `request_id` - including one carrying a now-stale `expected_version`,
as a real client retry would - finds that marker already written and returns its recorded version
as a no-op instead of raising `VersionConflict` or applying `events` twice; `request_id=None`
(the default) leaves `append`'s behavior unchanged from 1.3. `create_game` needs no equivalent,
since `game_id` is already its idempotency key (`GameAlreadyExists` on a repeat). Engine `Move`/
`Event` types, `apply_move` and `t42.storage.replay` stay untouched - idempotency is a repository
concern only (invariant 1).

1.5 (player-specific view) is complete: `t42.engine.projection.project(state, player_id)` is the
one gate hidden information passes through (invariant 5). Almost everything on `GameState` turns
out to already be public at a real table - the auction, tricks, marks, declarer and contract - so
`project()` mostly copies those fields to plain dict/list/str/int/None data, substitutes the
caller's own tiles for the full `HandState.hands` mapping, and calls `game.legal_moves` directly
for the `legal_moves` field rather than re-deriving whose turn it is. Its small encoders are
deliberately not shared with `t42.storage.codec`: `t42.engine` may not import from `t42.storage`
(invariant 1), and the two serve different purposes - a durable wire format versus a client
read-model. Proven in `tests/engine/test_projection.py` by a leakage test that drives real games
(standard and nello, the latter for its sitting-out partner) through every phase and asserts no
tile held by another seat ever appears anywhere in the projected structure.

Integration tests against DynamoDB Local (1.6) are next - see ROADMAP.md.

## Layout

```
src/t42/engine/     pure rules library (Phase 0 - complete)
    dominoes.py     the 28 tiles, a-b notation
    suits.py        trump membership, led suit, follow, ranking, doubles-own-suit variant
    scoring.py      count-domino values, hand point totals
    house_rules.py  per-game HouseRules (rule variants), incl. contract_options
    trick_rules.py  shared follow-suit legality and highest-trump-or-led-suit winner
    contracts/      Contract protocol, name-keyed registry, all six contract strategies
    state.py        frozen dataclasses: GameState, HandState, Trick, PendingBid
    events.py       immutable log events (the persistence contract)
    moves.py        what a client may propose
    bidding.py      auction state machine, incl. plunge confirmation and dealer-must-bid
    tricks.py       trick legality and resolution, active-seat-aware for nello's 3-handed hands
    game.py         new_game / apply_move / legal_moves entry points
    errors.py       RulesError, IllegalMove, OutOfTurn, UnknownContract
    projection.py   player-specific view                                   stub (Phase 1)
src/t42/storage/    DynamoDB event log + materialized state   (Phase 1, in progress)
    codec.py        GameState/HouseRules/Event <-> plain attribute maps (1.1 - complete)
    events.py       move/deal -> Event (write direction)                (1.2 - complete)
    replay.py       Event log -> GameState via real new_game/apply_move (1.2 - complete)
    repository.py   create_game/get_state/append against DynamoDB       (1.3 - complete)
    errors.py       GameNotFound, GameAlreadyExists, VersionConflict    (1.3 - complete)
src/t42/api/        Lambda handlers behind API Gateway        (Phase 2, not created)
src/t42/cli/        thin command-line client                  (Phase 3, not created)
tests/engine/       mirrors the engine modules; test_full_game.py is the Phase 0 milestone demo;
                    _helpers.py's `drive_to_game_over`/`prefer_contract` (plus its `on_state`/
                    `on_transition` hooks) are reused by tests/storage/ to generate real games for
                    the codec, replay and repository round-trip tests
tests/storage/      mirrors src/t42/storage/; conftest.py's `table` fixture is a moto-backed
                    in-memory DynamoDB table, used by test_repository.py (real DynamoDB Local is
                    reserved for 1.6's integration tests)
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
   lives on `HouseRules` and is threaded through as an argument. Two games under different variants
   must score and replay correctly in the same process. This includes each contract's own terms:
   a bid minimum belongs in `contract_options` (DESIGN.md §5.1), never as a class attribute on the
   registered contract, because that singleton is shared by every game in the process.
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
  green suite always means what it says. Only `projection.py` is still a stub.
- Contract rule variants (plunge/splash doubles-and-marks minimums, nello doubles handling,
  sevens tie-breaking, all-pass) are resolved and recorded in DESIGN.md §12 - read there before
  assuming a different regional rule.
