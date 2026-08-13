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

## Phase 2.7: Tables - rule sets, invites, visibility

Goal: everything about setting a table up, finished before the CLI is written. Saved house-rule
sets, tables that are public or invite-only, invites addressed by username, and a browse of public
tables with seats free.

This lands before Phase 3 for the same reason Phase 0.5 landed before Phase 1: the CLI's command set
should be written once against the finished surface rather than grown into it, and three of these
four features add commands.

It is a fractional phase so that Phase 3 stays the CLI and nothing downstream renumbers. The
fraction is **2.7** rather than the more natural 2.5 because Phase 2 already has a subsection 2.5
(contract tests), cited by name from several test modules - "ROADMAP.md 2.5" has to keep meaning one
thing. Phase 2's last subsection is 2.6, so 2.7 is simply the next free number after it.

Semantics are settled in DESIGN.md §5.1 (saved sets), §6.2 (visibility and invites) and §4.1 (the
new item shapes and the `OpenGames` index) - read those first. Two decisions from there shape the
work below: applying a saved set **copies** it, and an invite is a **permission grant** rather than
a seat reservation.

### 2.7.1 Saved rule sets

`t42/storage/rule_sets.py` and one new item type, `PLAYER#<id> / RULESET#<ruleSetId>`, holding a
display name and the encoded `HouseRules`.

- `create_rule_set`, `get_rule_set`, `list_rule_sets`, `update_rule_set`, `delete_rule_set`, plus a
  `RuleSetNotFound` under the existing `StorageError` base. Reuse `codec.encode_house_rules` /
  `decode_house_rules` - the stored config is the same shape as `META.config`, deliberately, so
  there is no second encoder to keep in step.
- **Validate on save**, through `contracts.validate_house_rules`, for the same reason
  `create_pending_game` does rather than deferring to `new_game`: a set that only fails at the table
  is a trap saved weeks earlier.
- `update_rule_set` is a full replace of name and rules, conditioned on `attribute_exists(SK)`, so
  editing something already deleted is an error rather than a resurrection.
- Five endpoints under `/players/me/rule-sets` (DESIGN.md §6). Authorization needs no check of its
  own: the items live in the caller's own partition, so somebody else's id is a miss, not a leak.
- `CreateGameRequest` gains `rule_set_id`, mutually exclusive with the inline `house_rules` body.
  Detecting "supplied both" needs a pydantic `model_validator` reading `model_fields_set`, because
  `house_rules` has a `default_factory` and an absent field is otherwise indistinguishable from a
  defaulted one.

Self-contained and changes no existing behaviour, so it goes first.

### 2.7.2 Visibility and invites

- `Visibility` (`public`/`invite_only`) on `META`, carried on `Lobby`, defaulting to `public` -
  which is exactly today's behaviour, so the existing suite must pass unchanged. `get_lobby` reads
  the attribute directly with no `.get()` fallback, matching the codec's stance that a new field is
  a migration point; nothing is deployed, so there is no data to migrate.
- `t42/storage/invites.py`: the `GAME#/INVITE#` and `PLAYER#/INVITE#` pair written and deleted in
  one `transact_write`, plus `invite_player`, `find_invite`, `list_invites_for_player`,
  `revoke_invite`. `invite_player` is idempotent - re-inviting overwrites and returns, since clients
  retry.
- **The check goes inside `join_seat`**, after the existing held-seat/status/seat-taken checks and
  before the conditional claim, raising a new `NotInvited`. Storage stays the single authority on
  who may sit down. Document the read-then-write window in the docstring, as that module already
  does for its other races - the reasoning is in DESIGN.md §6.2 and the short version is that
  promoting the claim to a transaction would cost the error attribution the claim depends on.
- A successful claim revokes the invite, so it leaves the invitee's pending list.
- Three endpoints (DESIGN.md §6). `POST /games/{id}/invites` takes a username, which needs a new
  `accounts.player_for_username` - only `authenticate` reads the `USERNAME#` item today, and
  privately - plus a `PlayerNotFound`. Reject inviting somebody already seated, or into a game past
  `WAITING`.
- `GET /players/me/invites` enriches each row with a `get_lobby` read for seat counts and house
  rules and drops games no longer `WAITING`. A bounded N+1 over a handful of pending invites, in
  exchange for a list that is never stale; keep the enrichment in the handler and the storage
  function a dumb row read.
- **`GET /games/{id}` authorization widens** to seated / invited-or-public-waiting / everybody else
  (DESIGN.md §6.2). The mechanical change is that `_game_response` projects when the caller is
  **seated**, replacing today's test of whether the game has been dealt.

### 2.7.3 Open-games browse

- The `OpenGames` GSI goes into `tests/conftest.py`'s `_create_texas42_table`, which both the moto
  and DynamoDB-Local fixtures already build from, so the schema cannot drift between them.
- `create_pending_game` writes `GSI1PK`/`GSI1SK` only for a public game; `start_game`'s `META`
  update gains `REMOVE GSI1PK, GSI1SK`. That update is the only exit from `WAITING`, so there is no
  second removal site to remember.
- `lobby.list_open_games(table, *, limit)`: one query on the index, `ScanIndexForward=False`.
- `GET /games/open` filters out tables the caller is already seated in - free, since the index
  projects `ALL` and the seats map comes along.

### 2.7.4 Tests

Same split the repo already uses: storage against moto, API through `TestClient` only, nothing
reaching past the API into storage.

- `tests/storage/test_rule_sets.py` - CRUD; an incoherent set is rejected at save; one player cannot
  read another's.
- `tests/storage/test_invites.py` - both items written and both deleted; `join_seat` refuses an
  uninvited player on an invite-only game, consumes the invite on success, and is unaffected on a
  public one.
- `tests/storage/test_lobby.py` - `list_open_games` is newest-first, excludes invite-only games, and
  a game leaves the index when dealt.
- `tests/api/test_rule_sets.py` - the contract matrix; a game created from a saved set; **the
  snapshot guarantee**: edit the set afterwards and assert the game's rules are unchanged. A foreign
  `rule_set_id` is 404; supplying both `rule_set_id` and `house_rules` is 400.
- `tests/api/test_invites.py` - invite by username, it appears in the invitee's list, they join, it
  disappears; an uninvited join is 403; an invitee reading the game gets `view: null`; a stranger
  gets 403.
- `tests/api/test_open_games.py` - a public table appears, an invite-only one does not, a dealt one
  drops off, and the caller's own tables are filtered out.
- `tests/storage/test_lobby_integration.py`, marked `integration` - the index against real DynamoDB
  Local, **polling** rather than asserting immediately. GSI propagation is asynchronous and moto is
  strongly consistent, so this is the one guarantee moto cannot establish.

### Exit criteria

- A rule set survives save, edit and apply, and a table created from one is immune to later edits to
  it - proven by test, since this is a guarantee and not just current behaviour
- An invite-only table cannot be joined by an uninvited player, and a consumed invite disappears
- A public table appears in the browse and leaves it when dealt
- `GET /games/{id}` never projects for a caller who is not seated
- The default suite passes unchanged apart from additions: `public` is the default, so nothing that
  existed before this phase changes meaning

---

## Later phases

- **Phase 3, CLI**: the command set in DESIGN.md §7 plus the Phase 2.7 surface - saving and applying
  rule sets, creating an invite-only table, inviting by username, and browsing open tables - then a
  dogfooded 4-player game
- **Phase 4, Notifications**: DynamoDB Streams to Lambda to SES, verified across a real delay.
  Also the natural home for the deferred account work: password reset and email verification,
  which need a send channel and have none before this point
- **Phase 5, Hardening**: abandoned games, CLI errors and help, observability, login rate limiting
- **Phase 6, Bot players**: DESIGN.md §13. Bot accounts, a uniform-random-legal policy over the
  projected view's `legal_moves`, and a Streams-driven turn trigger reusing Phase 4's plumbing. Last
  on purpose - a bot is a client of the finished API, so everything else has to work first

### Open sequencing question: when does anything get deployed?

Phase 3 was written as "the CLI against the deployed API", but no phase provisions anything until
Phase 5's deploy scripting, so as written the CLI has nothing to point at. Phase 2 ends with a
Mangum entry point and an app that runs under `uvicorn` against DynamoDB Local, which is enough to
build and test the CLI against, so this is not urgent. It needs deciding before Phase 3 ends:
either pull a minimal stack (table, one Lambda, one HTTP API, IAM) forward out of Phase 5, or
accept that dogfooding happens against a locally hosted API.
