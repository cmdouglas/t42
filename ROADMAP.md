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

`projection.py` is a Phase 1 stub - the player-specific view lands with persistence, since it's
naturally exercised against a real game log (see Phase 1, 1.5 below).

---

## Phase 1: Persistence

Goal: durable games in DynamoDB, with the event log as the source of truth and a materialized
state item for fast reads. Depends on Phase 0 exit criteria.

### 1.1 Item shapes and codec

`t42/storage/`, single table per DESIGN.md §4.1 (`META`, `EVENT#<seq>`, `STATE`, `PLAYER#`).

- Encode and decode events, `GameState` and `RuleConfig` to plain DynamoDB attribute maps
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
