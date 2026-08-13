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

Phase 1 (persistence) is complete. boto3 landed in 1.3 - see below.

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
optimistic-concurrency guarantee 1.6 exercises under real concurrency. `version` lives only in
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

1.6 (integration tests) is complete, closing out Phase 1. `tests/storage/conftest.py`'s
`dynamodb_local` fixture starts a real `amazon/dynamodb-local` container via `testcontainers` for
the whole test session and `real_table` creates/drops a fresh `Texas42` table in it per test - the
same per-test isolation `table`'s moto fixture gives, just against a long-lived container. Both
fixtures create their table through the shared `_create_texas42_table` helper, so the schema can't
drift between the two. These tests are marked `@pytest.mark.integration` and excluded from the
default `uv run pytest` (`addopts` carries `-m "not integration"`) since they need Docker and are
slower to start; `uv run pytest -m integration` runs them explicitly, and CI runs both as separate
steps. `tests/storage/test_repository_integration.py` proves, against real infra rather than
moto's approximation of it, the two guarantees moto alone couldn't fully establish: genuine
concurrent `append` calls from a `ThreadPoolExecutor` racing the same `expected_version` never let
more than one land or produce a mixed state, and a full scripted game persisted move by move
round-trips through `replay()` exactly as the moto-backed version does. With this, Phase 1's exit
criteria (ROADMAP.md) are all met.

Phase 2 (API) is complete: a FastAPI app behind Mangum implementing DESIGN.md §6, with every
endpoint covered by the four-case contract matrix and a full game playable signup-to-`GAME_OVER`
over HTTP. It settled the two things DESIGN.md left open, both recorded there:

- **Identity** (§6.1, §12): username + password minting **per-device bearer tokens**, hashed with
  stdlib `scrypt` (passwords) and `sha256` (tokens, being high-entropy). A player holds many
  tokens, so signing in on a phone leaves a desktop alone and losing one device revokes one
  credential. `PlayerId` is opaque, never the username, so usernames stay renameable and never
  enter the immutable event log. Contacts are a list of `{kind, address, verified}` channels, not
  an `email` field, so Phase 4 adds a branch rather than a migration. `t42/storage/accounts.py`.
- **The lobby** (§4.1): a game is created `WAITING` with only its creator seated, and the join
  that fills the fourth seat deals and flips it to `ACTIVE` - conditioned on the status still
  being `WAITING`, which is what makes two simultaneous fourth joins deal exactly once. It lives
  entirely in `t42/storage/lobby.py`; the engine still has no notion of a partially seated game.
  This reworked `repository.create_game` into `start_game`, whose `META` write is now a
  conditional `Update` rather than a `Put`.

Two things worth knowing before touching the API layer:

- **`GameResponse.view` is deliberately opaque.** It carries `project()`'s output verbatim rather
  than through a pydantic model mirroring it. A model would be a second definition of the
  projected shape sitting next to the one gate invariant 5 requires, free to drift - and a
  drifted mirror is how a field leaks. The cost is a vaguer OpenAPI schema for that one field.
- **An idempotency key is checked twice**, before the move and again after a rejection. 1.4's
  marker inside `append` is necessary but not sufficient once a handler sits on top: the handler
  re-derives the move from fresh state, so a retry arriving after the turn moved on is rejected
  as out-of-turn long before `append` ever sees the marker. `repository.find_request` is the
  up-front look; the second look catches parallel retries that both miss it. See `api/app.py`'s
  `_submit`, which is the single write path behind all three move endpoints.

Deployment is deliberately not part of Phase 2 - there is a Mangum entry point and nothing
provisioned. ROADMAP.md carries the open sequencing question about when that changes.

Phase 3 (CLI) is next - see ROADMAP.md.

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
    projection.py   project(state, player_id): the hidden-information gate (1.5 - complete)
src/t42/storage/    DynamoDB event log + materialized state   (Phases 1 and 2, complete)
    _dynamo.py      shared boto3 plumbing: transact_write, Decimal and str narrowing
    codec.py        GameState/HouseRules/Event <-> plain attribute maps (1.1)
    events.py       move/deal -> Event (write direction)                (1.2)
    replay.py       Event log -> GameState via real new_game/apply_move (1.2)
    repository.py   start_game/get_state/append/find_request, GameStatus (1.3, 1.4, 2.2)
    lobby.py        create_pending_game/join_seat/list_games_for_player  (2.2)
    accounts.py     players, passwords, per-device bearer tokens         (2.1)
    errors.py       GameNotFound, VersionConflict, SeatTaken, InvalidToken, ...
src/t42/api/        FastAPI app behind Mangum                 (Phase 2, complete)
    app.py          the eleven endpoints; `_submit` is the one write path for moves (2.4)
    deps.py         table handle and the bearer-token dependency, both overridable (2.4)
    schemas.py      pydantic request/response bodies; the bid body is discriminated (2.3)
    errors.py       domain exception -> status code + machine-readable code          (2.3)
    lambda_handler.py  `Mangum(app)`, nothing else                                   (2.6)
src/t42/cli/        thin command-line client                  (Phase 3, not created)
tests/conftest.py   the `table` (moto) and `real_table` (DynamoDB Local via testcontainers)
                    fixtures, shared by tests/storage/ and tests/api/
tests/engine/       mirrors the engine modules; test_full_game.py is the Phase 0 milestone demo;
                    _helpers.py's `drive_to_game_over`/`prefer_contract` (plus its `on_state`/
                    `on_transition` hooks) are reused by tests/storage/ to generate real games for
                    the codec, replay and repository round-trip tests
tests/storage/      mirrors src/t42/storage/; _helpers.py's `started_game` reaches a dealt game
                    the way a real one is reached, through the lobby rather than around it
tests/api/          contract tests over FastAPI's in-process TestClient, with `table` injected
                    via `app.dependency_overrides`; _helpers.py's `Client`/`play_until` drive a
                    whole game over HTTP, and every test goes through the public API only
```

## Commands

Requires [uv](https://docs.astral.sh/uv/); Python 3.13 is fetched automatically.

```bash
uv sync --extra dev            # venv + dev tooling
uv run pytest                  # tests (fast; excludes the Docker-backed integration suite)
uv run pytest -m integration   # integration tests against a real DynamoDB Local (needs Docker)
uv run mypy                    # strict type check over src and tests
uv run ruff check .            # lint
uv run ruff format .           # format
```

Run `pytest`, `mypy`, `ruff check` and `ruff format` before considering a change done; CI runs the
same set, plus the integration suite as its own step.

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
   decides what a player may see. No handler or client may hand out anything else, and nothing
   may re-declare the projected shape - a response model mirroring it would be a second
   definition free to drift from the gate, so `GameResponse.view` passes it through opaquely.
   `tests/api/test_moves.py` sweeps every response of a whole game to prove nothing leaks at the
   wire, not just at `project()`.
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
