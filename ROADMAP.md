# Roadmap

Execution breakdown for the phases in [DESIGN.md](DESIGN.md) §10. Phases 0 and 1 are broken down
in full; later phases are sketched and will be expanded as they come up.

Scaffolding is committed: toolchain, engine module layout, and the implemented primitives listed
under "Done" below.

---

## Phase 0: Rules engine — complete

Goal: a pure library that can run a complete 4-player game in memory, with no network and no AWS.
All six contracts (standard, nello, nello_low, sevens, plunge, splash) are implemented; a full
game per contract runs end to end through `new_game`/`apply_move`/`legal_moves` in
`tests/engine/test_full_game.py`, the Phase 0 milestone demo. The rule-variant decisions this
phase depended on (0.1, below) are recorded in DESIGN.md §12.

### Done

- `dominoes.py`: tile representation, normalized ends, `a-b` notation
- `suits.py`: trump membership, led suit, follow legality, rank within a suit, doubles-as-own-suit
  variant, doubles-rank-low variant (for `nello_low`)
- `scoring.py`: count values, 35 count + 7 tricks = 42
- `config.py`: per-game `RuleConfig`
- `trick_rules.py`: shared follow-suit legality and highest-trump-or-led-suit winner, reused by
  every contract except sevens (its own pip-distance winner)
- `contracts/`: registry plus all six strategies (`standard`, `nello`, `nello_low`, `sevens`,
  `plunge`, `splash`)
- `state.py` / `events.py` / `moves.py`: data shapes, including `PendingBid`/`ConfirmBid` for the
  plunge confirmation sub-flow
- `bidding.py`: full auction state machine - numeric and mark bids, plunge confirmation (public,
  not a private channel - see DESIGN.md §12), the dealer-must-bid rule that replaces an all-pass
  redeal
- `tricks.py`: trick legality and resolution, active-seat-aware so nello's 3-handed hand closes
  tricks at 3 plays instead of 4
- `game.py`: `new_game`, `apply_move`, `legal_moves` - dealing, hand lifecycle, phase dispatch

### 0.1 Rule variants — resolved, see DESIGN.md §12

Plunge/splash doubles-and-marks minimums, nello's two doubles-ranking contracts, sevens'
tie-breaking, and the dealer-must-bid all-pass rule are all recorded there.

### Exit criteria — met

- A whole game runs end to end in memory, for every one of the six contracts
- Illegal moves raise `RulesError`, never corrupt state (state is immutable throughout; verified)
- No I/O, no AWS import anywhere under `t42.engine`
- The rules modules carry the heaviest test investment: scoring boundaries, follow-suit edge
  cases, and a property test that a trick always has exactly one winner

### Still open (tracked, not blocking)

- `projection.py` is a Phase 1 stub - the player-specific view lands with persistence, since it's
  naturally exercised against a real game log (see Phase 1, 1.5 below).
- Each contract's bid entry bar (plunge's 4 doubles / 4 marks, splash's 3 / 2, nello's and sevens'
  1 mark) is a class attribute or module constant rather than per-game data. Phase 0.5 lifts these
  into house-rule options.

---

## Phase 0.5: House rules

Goal: a game is created with an explicit, validated house-rule set, and no contract-specific rule
value survives as a global. Everything a table might rule differently is data on one `HouseRules`
value; an incoherent rule set is rejected at creation rather than surfacing mid-auction.

This lands before Phase 1 on purpose: 1.1's codec encodes the rule config to DynamoDB and §4.1
stores it on the `META` item, so settling the shape afterwards would be a data migration.

Model and validation tiers are defined in DESIGN.md §5.1 - read that first.

### 0.5.1 Rename `RuleConfig` to `HouseRules`

`config.py` becomes `house_rules.py`. Mechanical: 114 references across 29 files, all caught by
mypy and ruff. Its own commit, so the behavioural change in 0.5.2 reviews cleanly. No data
migration - Phase 1 storage does not exist yet.

### 0.5.2 Contract-declared options

- `Contract` protocol gains `option_defaults()` and `validate_options(options, rules)`
- `HouseRules` gains `contract_options` and the `options_for(name)` merge helper
- Convert the four hardcoded sites listed under Phase 0 "Still open" to declared options, keeping
  today's values as the defaults, so an unconfigured game behaves exactly as it does now
- `_partner_declares_common.py` and `_nello_common.py` read their minimums through `options_for`
  instead of `self._minimum_*` and module constants; `plunge.py` and `splash.py` shrink to a name,
  their defaults, and `_requires_confirmation`

### 0.5.3 Validation

`contracts.validate_house_rules(rules)` covering the three tiers in DESIGN.md §5.1, retiring
today's `validate_enabled`, and **called from `game.py: new_game`** - it currently has no callers
at all, so a game can presently be created naming a contract that does not exist and only fails
mid-auction inside `legal_bids`. The plunge/splash coherence check lives in those two contracts,
not in the core.

### 0.5.4 Tests

`tests/engine/test_house_rules.py`:

- Defaults reproduce current behaviour exactly
- An override changes which bids `legal_bids` offers
- Each validation tier rejects its own case with a clear message: unknown contract, options for a
  disabled contract, unknown option key, a doubles minimum of 8, a mark minimum of 8, and a splash
  bar harder than plunge's on either axis (the two contracts inverted - DESIGN.md §5.1 tier 3)
- The default bars validate clean, including the plunge-dominated-by-splash case that DESIGN.md
  §5.1 explicitly declines to reject
- `nello` + `nello_low` enabled together validates clean (DESIGN.md §12)
- The regression that motivates the phase: two games alive in one process under different plunge
  minimums, where a hand legal in one is rejected in the other - impossible while the minimum
  lives on the registry singleton

Extend `tests/engine/test_full_game.py` with a full game under non-default house rules.

### 0.5.5 Declared leads

The first game-wide mechanic to go behind a house-rule flag, per DESIGN.md §5.2:
`allow_declared_lead` of `never` (default) / `first_trick` / `always`, letting a leader name which
end of their tile is the suit led.

This belongs in Phase 0.5 rather than later because it adds a field to `DominoPlayed`. Before
Phase 1 that is a dataclass edit; after it, a data migration (invariant 6).

The change is small because the led suit is computed in exactly two places, both in
`trick_rules.py`, and every contract routes through them:

- `Trick` gains `declared_suit: Suit | None`; `PlayDomino` and `DominoPlayed` gain the same field.
  It has to be on the event - the suit led is no longer recoverable from the tile, so a log
  without it cannot be replayed
- New `suit_led(trick, trump, rules)` helper replaces the `led_suit()` calls in
  `follow_suit_plays` and `highest_trump_or_led_suit_wins`. No contract module changes
- `tricks.py: play` validates the declaration (leader only, a suit the tile belongs to, neither
  end trump, and the trick index permitted by the setting) and records it on the trick
- `game.py: legal_moves` enumerates `(tile, declaration)` pairs rather than bare tiles, so a
  client can render the two ways of leading `3-2` as the distinct moves they are
- `rank_in_suit` needs no change: it already ranks a tile by its other end relative to whichever
  suit it is asked about

**Write this regression first.** `tricks.py:70-71` currently builds fresh `Trick` objects
(`Trick(plays=new_plays)`) when closing a trick, rather than carrying the existing one forward.
With a defaulted `declared_suit` that still compiles, type-checks and passes every existing test
while silently discarding the declaration on the trick that closes, which is the one place it
decides the winner. Both sites become `replace(hand.current_trick, ...)`.

Tests in `tests/engine/test_declared_leads.py`: `never` reproduces today's behaviour exactly;
`first_trick` permits a declaration on trick 1 and rejects one on trick 2; `always` permits both;
a declared lead changes which tiles the other seats may legally play, and changes the trick winner
where the two readings disagree; declaring a suit the tile does not belong to is rejected; a tile
with a trump end cannot be declared out of trump; doubles offer no declaration under either
`doubles_are_own_suit` setting; a full game under `always` still reaches `GAME_OVER`.

### Exit criteria

- No contract-specific rule value survives as a class attribute or module constant
- `new_game` rejects an incoherent rule set; no invalid rule set can produce a game
- Two concurrent games under different house rules score and replay correctly
- Default `HouseRules()` behaves identically to today, proven by the existing suite passing
  unchanged apart from the rename
- A declared lead survives a trick closing, and is recorded on the event log rather than derived

---

## Phase 1: Persistence

Goal: durable games in DynamoDB, with the event log as the source of truth and a materialized
state item for fast reads. Depends on Phase 0 and Phase 0.5 exit criteria - the codec below
encodes `HouseRules`, so its shape must be settled first.

### 1.1 Item shapes and codec

`t42/storage/`, single table per DESIGN.md §4.1 (`META`, `EVENT#<seq>`, `STATE`, `PLAYER#`).

- Encode and decode events, `GameState` and `HouseRules` - including its nested `contract_options`
  map - to plain DynamoDB attribute maps
- Round-trip property test over generated states: `decode(encode(x)) == x`
- Keep the codec separate from the repository so it can be tested with no database

Note: engine dataclasses are the wire format's source of truth. Adding a field is a data
migration, and the codec is where the compatibility shim would live.

### 1.2 Replay

`replay(events) -> GameState`, rebuilding state from `HandDealt` forward using the same
`apply_move` path as live play, so replay and play cannot diverge.

Test: for a game played in memory, replaying its event log reproduces the final state exactly.

### 1.3 Repository writes

- `append(game_id, event, expected_version)`: `TransactWriteItems` writing `EVENT#<seq>` and the
  updated `STATE` together, conditioned on `version`, plus the `PLAYER#` turn-status items
- Stale `version` surfaces as a typed conflict error the API layer can turn into a 409
- Update `last_activity_at` on every write (DESIGN.md §9, so the abandoned-game feature needs no
  migration later)

### 1.4 Idempotency

Store the client request ID with the event and condition the write on its absence; a duplicate
submission returns the prior result rather than applying twice.

Test: submitting the same move twice yields one event and identical responses.

### 1.5 Player-specific view

`projection.py: project(state, player_id)`.

- Strip other seats' hands and any undealt tiles; include own hand, trump, current trick,
  completed tricks, marks, whose turn, and legal moves when it is the caller's turn
- Return plain JSON-able data with nothing CLI-specific (DESIGN.md §11)

Tests: for every seat, the projection contains no tile held by another seat; a leakage test that
walks the projected structure and asserts no foreign tile appears anywhere in it.

### 1.6 Integration tests

Against DynamoDB Local: create, append, read back, concurrent conflicting writes, idempotent
replay of a duplicate request, and a full scripted game persisted move by move.

### Exit criteria

- A game plays to completion through the storage layer, one process at a time
- Concurrent writes to the same game cannot interleave into a corrupt state
- Replaying any game's log reproduces its `STATE` item
- Projection leaks nothing, proven by test rather than inspection

---

## Phase 2: API

Goal: the engine reachable over HTTP. FastAPI handlers over `apply_move` plus the repository,
behind a Mangum adapter for Lambda, implementing the endpoint set in DESIGN.md §6 with
per-endpoint contract tests.

Two things DESIGN.md left open have to be settled here, and both are data-model decisions rather
than handler details, so they come first:

- **Player identity**, §12's open question, resolved there: username plus password, minting
  per-device bearer tokens. See 2.1.
- **The lobby.** §6 has `POST /games` then `POST /games/{id}/join`, but `repository.create_game`
  requires all four seats and deals immediately, so there is no representation of a game waiting
  for players. See 2.2.

Deployment is deliberately **not** in this phase. It stays in Phase 5 until the handlers exist and
the shape of what needs provisioning is settled by working code rather than guessed at.

### 2.1 Accounts and tokens

`t42/storage/accounts.py`, adding four item types to the existing single table (DESIGN.md §4.1) -
no GSI, no second table:

| PK | SK | Purpose |
|---|---|---|
| `PLAYER#<id>` | `PROFILE` | username, contact channels, created_at |
| `TOKEN#<sha256(token)>` | `TOKEN` | player_id, device label, created_at, last_used_at, expires_at |
| `PLAYER#<id>` | `TOKEN#<sha256>` | reverse lookup, so a player can list and revoke devices |
| `USERNAME#<lowercased>` | `PLAYER` | uniqueness reservation via conditional put |

- `create_player`, `authenticate`, `issue_token`, `player_for_token`, `revoke_token`,
  `list_tokens`. New `UsernameTaken`, `InvalidCredentials` and `InvalidToken` under the existing
  `StorageError` base.
- **Passwords use stdlib `hashlib.scrypt`, tokens use sha256.** A token is a high-entropy random
  value, so a fast hash is the right one for it and a slow one is right for a password. No new
  dependency either way. Store the salt and parameters alongside the password hash; compare with
  `hmac.compare_digest`.
- **A player has many tokens, one per device**, so signing in on a phone does not disturb a
  desktop and losing one device revokes one token. No expiry; revocation is explicit. The
  `expires_at` attribute is written anyway so adding expiry later is not a migration.
- **`PlayerId` stays opaque**, not the username, so usernames stay renameable and never get
  embedded in the event log.
- **Contacts are a list of channels**, `{"kind": "email", "address": ..., "verified": false}`,
  not a bare `email` attribute - Phase 4 then branches on `kind` and adding SMS or a chat DM is a
  new branch rather than a migration. Same argument DESIGN.md §9 makes for `last_activity_at`.

### 2.2 Lobby

`t42/storage/lobby.py`, plus a rework of `repository.create_game`. The lobby lives entirely in the
storage layer: `META` gains `status` and a partial seats map, and the engine is untouched -
`new_game` still takes four seats and deals.

- `create_pending_game` writes `META` with `status="WAITING"` and a one-seat map. It must call
  `contracts.validate_house_rules` itself, since `new_game` will not run until the deal and an
  invalid rule set would otherwise sit in a lobby until the fourth player joined.
- `join_seat` conditionally claims an empty seat while `status="WAITING"`. Re-joining a seat you
  already hold is a no-op success, not a conflict.
- `list_games_for_player` is one `Query` on `PK = PLAYER#<id>`. The `PLAYER#<id> / GAME#<id>`
  items gain `status` so this needs no fan-out; `append` already rewrites all four of them on
  every move, so carrying it is nearly free.
- `create_game` is **reworked, not just renamed**, into `start_game`. `META` already exists by
  then, so its `Put` with `attribute_not_exists(PK)` becomes an `Update` flipping `status` from
  `WAITING` to `ACTIVE`, conditioned on `status = "WAITING"`. That condition is what makes two
  simultaneous fourth joins deal exactly once. The `HAND_DEALT` event, `STATE` and the `PLAYER#`
  turn-status writes are unchanged.
- The game id doubles as the join code (DESIGN.md §2): six characters from an alphabet with no
  `I`, `L`, `O`, `U`, `0` or `1`. Collisions surface as the existing `GameAlreadyExists`.
- Seat labels are denormalized onto `META` at join time, so rendering a view needs no profile
  reads.

### 2.3 Schemas and error mapping

`t42/api/schemas.py` and `t42/api/errors.py`.

- The bid body is a **discriminated union** on `kind` (`BID`/`PASS`/`CONFIRM_BID`), mapping 1:1
  onto the engine's move alphabet. This is where the plunge confirmation lives; §6 lists no
  endpoint for it, and folding it into the auction endpoint beats inventing a fourth move route.
- `HouseRulesRequest` converts to `HouseRules` and lets `__post_init__` plus
  `contracts.validate_house_rules` do the real checking, rather than restating rules in pydantic.
- **Responses do not re-declare the projection.** The game response is a thin wrapper carrying
  `project()` output opaquely under `view`. A pydantic mirror of the projected shape would put a
  second definition of it next to the single gate invariant 5 requires, and the two would drift.
- Error mapping, each with a machine-readable `code` so the Phase 3 CLI can branch: 401 for a
  missing or invalid token, 403 for a caller not seated in the game, 404 `GameNotFound`, 409 for
  `UsernameTaken`/`SeatTaken`/`VersionConflict`/`OutOfTurn`, 400 for `RulesError` and an invalid
  rule set. Rules rejections are 400 rather than 422 so they stay distinguishable from FastAPI's
  own validation failures, which already own 422.

### 2.4 Routes

`t42/api/app.py` and `t42/api/deps.py`: `POST /players`, `POST /sessions`,
`DELETE /sessions/current`, `GET /players/me`, `POST /games`, `POST /games/{id}/join`,
`GET /games/{id}`, `GET /players/me/games`, `POST /games/{id}/bid`, `POST /games/{id}/contract`,
`POST /games/{id}/play`.

One shared helper sits behind the three move endpoints and is the heart of the phase: `get_state`,
build the `Move`, `apply_move`, `events_for_move`, `append` with the read version and the
`Idempotency-Key` header as `request_id`, then `project`.

- **`VersionConflict` returns 409 with no automatic retry.** Real contention cannot happen in a
  turn-based game: a second player submitting concurrently is rejected as `OutOfTurn` first, and a
  double submission by the same player is absorbed by 1.4's idempotency marker. A retry loop would
  be machinery guarding nothing.
- The client never supplies a version - the server reads the current one itself - so `version`
  stays off the wire entirely.
- `GET /games/{id}` returns the lobby shape while `WAITING`, since no `STATE` item exists yet.

### 2.5 Contract tests

`tests/api/`, over FastAPI's `TestClient` with the moto-backed `table` fixture injected through
`app.dependency_overrides`. TestClient runs in-process, so there is no HTTP mocking. The `table`
fixture and `_create_texas42_table` move up to a top-level `tests/conftest.py` so both
`tests/storage/` and `tests/api/` can use them.

- The four-case matrix from DESIGN.md §10 per mutating endpoint: valid move, invalid move, out of
  turn, stale version. The stale case is forced by monkeypatching `repository.get_state` to return
  a `StoredGame` one version behind.
- Auth: no header, malformed header, revoked token, and a valid token for a player not seated.
- Idempotency: the same `Idempotency-Key` twice yields one event and identical responses.
- **Leakage at the HTTP boundary**: drive a full game through the API and assert that no response
  any of the four players receives contains a tile held by another seat, reusing the structure
  walker from `tests/engine/test_projection.py`. 1.5 proved this of `project()`; this proves it of
  what actually goes over the wire.

### 2.6 Lambda entry point and integration test

`t42/api/lambda_handler.py` is `Mangum(app)` and nothing else. `tests/api/test_api_integration.py`,
marked `integration`, plays a full scripted 4-player game from signup to `GAME_OVER` against the
`dynamodb_local` fixture from 1.6.

### Exit criteria

- Every endpoint in DESIGN.md §6 exists and is covered by the four-case contract matrix
- A full 4-player game runs signup to `GAME_OVER` over HTTP against real DynamoDB Local
- No response any player receives contains another seat's tiles, proven by test rather than
  inspection
- A duplicate submission with the same idempotency key is a no-op returning the prior result
- The engine remains pure: nothing under `t42.engine` imports from `t42.api` (invariant 1)

---

## Later phases

- **Phase 3, CLI**: the command set in DESIGN.md §7, then a dogfooded 4-player game
- **Phase 4, Notifications**: DynamoDB Streams to Lambda to SES, verified across a real delay.
  Also the natural home for the deferred account work: password reset and email verification,
  which need a send channel and have none before this point
- **Phase 5, Hardening**: abandoned games, CLI errors and help, observability, login rate limiting

### Open sequencing question: when does anything get deployed?

Phase 3 was written as "the CLI against the deployed API", but no phase provisions anything until
Phase 5's deploy scripting, so as written the CLI has nothing to point at. Phase 2 ends with a
Mangum entry point and an app that runs under `uvicorn` against DynamoDB Local, which is enough to
build and test the CLI against, so this is not urgent. It needs deciding before Phase 3 ends:
either pull a minimal stack (table, one Lambda, one HTTP API, IAM) forward out of Phase 5, or
accept that dogfooding happens against a locally hosted API.
