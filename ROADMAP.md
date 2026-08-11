# Roadmap

Execution breakdown for the phases in [DESIGN.md](DESIGN.md) §10. Phases 0 and 1 are broken down
in full; later phases are sketched and will be expanded as they come up.

Scaffolding is committed: toolchain, engine module layout, and the implemented primitives listed
under "Done" below.

---

## Phase 0: Rules engine

Goal: a pure library that can run a complete 4-player game in memory, with no network and no AWS.
This is the highest-risk, most logic-dense phase; it is finished before any infrastructure exists.

### Done

- `dominoes.py`: tile representation, normalized ends, `a-b` notation
- `suits.py`: trump membership, led suit, follow legality, rank within a suit, doubles-as-own-suit
  variant
- `scoring.py`: count values, 35 count + 7 tricks = 42
- `config.py`: per-game `RuleConfig`
- `contracts/registry.py`: name-keyed contract registry
- `state.py` / `events.py` / `moves.py`: data shapes (may still shift as logic lands)

### 0.1 Pin the rule variants (blocking)

DESIGN.md §12 leaves scoring variants open, and they change the shape of the contract
implementations. Settle before writing 0.4:

- Plunge: minimum doubles held (4 or 5), minimum mark bid, whether partner names trump and leads
- Sevens: tie-breaking when two tiles sit equally far from seven; whether a trump exists at all
- Splash: double requirement and mark minimum relative to plunge
- Nello: doubles handling (own suit high, own suit low, or in their number suits) and whether it
  is a fixed variant or another `RuleConfig` flag
- Whether an all-pass auction re-deals or forces the dealer to bid 30

Record the decision in DESIGN.md §12 rather than only in code.

### 0.2 Dealing and hand lifecycle

`game.py: new_game()`, plus the hand loop.

- Shuffle with an injected `random.Random` so deals are reproducible; deal 7 tiles per seat
- Emit `HandDealt` capturing the deal, so a hand replays exactly from the event log
- Advance dealer each hand; open the auction to the dealer's left
- Hand completion: score, add marks, either start the next hand or move to `Phase.GAME_OVER`
  at `config.marks_to_win`

Tests: deal is a partition of `FULL_SET` (28 tiles, no duplicates, 7 per seat); same seed gives the
same deal; dealer and turn order rotate correctly across several hands.

### 0.3 Bidding state machine

`bidding.py`, in order: `legal_bids` → `apply_bid` → `auction_is_settled` → `resolve_auction`.

- Numeric bids 30 to 42, each strictly above the previous; mark bids above those
- Mark bids carry the contract they are for, filtered by `config.enabled_contracts` and by the
  bidder's hand where the contract demands it (plunge, splash)
- Pass handling, out-of-turn rejection, all-pass resolution per 0.1
- `resolve_auction` sets declarer, winning bid and contract, and moves to `Phase.DECLARING`

Tests (table-driven): every legal and illegal bid at each auction position; out-of-turn; bidding
a disabled contract; plunge bid without the required doubles; all-pass; the auction as a whole
producing the right declarer.

### 0.4 Contract strategies

Implement against the `Contract` protocol, dropping the `UnimplementedContract` base as each
lands. Order: `standard` first (the others are defined by how they differ from it), then `nello`,
`sevens`, `plunge`, `splash`.

Each needs: `validate_bid`, `requires_declaration`, `opening_leader`, `sits_out`, `legal_plays`,
`trick_winner`, `score_hand`.

Tests per contract: a full scripted hand with known tiles and a known outcome, plus the scoring
boundary cases (bid exactly made, set by one point, all seven tricks).

### 0.5 Trick engine

`tricks.py`, delegating contract-specific behaviour to the active strategy rather than branching.

- `legal_plays`: whole hand when leading; tiles of the led suit when following and holding any
- `trick_winner`: highest trump, else highest tile of the led suit
- `play`: validate, append to the trick, close the trick and set the next leader, close the hand
  after seven tricks

Tests: follow-suit obligation under both doubles variants; trump beating a higher off-suit tile;
the trump double; a tile with two ends where only one follows; sevens ranking; property test that
across the 28 tiles exactly one seat wins every well-formed trick.

### 0.6 In-memory game demo

A test (not a script) that plays a full game from `new_game` to `Phase.GAME_OVER` through
`apply_move` with a seeded RNG and a scripted or simple-heuristic player. This is the DESIGN.md
§10 Phase 0 milestone and doubles as a regression net for later phases.

### Exit criteria

- A whole game runs end to end in memory, all contracts enabled
- Illegal moves raise `RulesError`, never corrupt state
- No I/O, no AWS import anywhere under `t42.engine`
- Coverage of the rules modules is high enough that the scoring and follow-suit branches are
  exercised deliberately, not incidentally

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
