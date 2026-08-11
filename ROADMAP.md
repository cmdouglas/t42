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

## Later phases

- **Phase 2, API**: Lambda handlers over `apply_move` + repository, API Gateway, API-key auth,
  per-endpoint contract tests (valid move, invalid move, out of turn, stale version)
- **Phase 3, CLI**: the command set in DESIGN.md §7 against the deployed API, then a dogfooded
  4-player game
- **Phase 4, Notifications**: DynamoDB Streams to Lambda to SES, verified across a real delay
- **Phase 5, Hardening**: abandoned games, CLI errors and help, deploy scripting, observability
