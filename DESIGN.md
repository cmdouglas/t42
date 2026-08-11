# Texas 42 Online — Design Document & MVP Development Plan

## 1. Goals

Build a server-authoritative, asynchronous implementation of Texas 42 (partnership domino trick-taking, with nello, plunge, and sevens as special contracts) that multiple client types can share. The MVP ships a command-line client only; the architecture should make adding a web app, mobile app, or chatbot client later a matter of writing a thin client against an existing API, not rewriting game logic.

Design priorities, in order: correctness of rules, no leakage of hidden information (hands, remaining dominoes) to the wrong player, and support for play spread across minutes or hours. Real-time performance is not a concern.

## 2. Scope for MVP

In scope:
- 4-player, fixed-partnership games (2v2, partners seated across from each other)
- Standard bidding (30–42, points-based) plus mark-based special contracts: nello, plunge, sevens
- Configurable rule variants selected at game creation: which special contracts are enabled (nello, plunge, sevens, splash, ...) and whether doubles count as their own suit
- Server-side move validation
- CLI client for creating/joining games, bidding, and playing
- Email notification when it's a player's turn
- Single region, single small DynamoDB table, no horizontal scaling concerns

Out of scope for MVP (noted for later):
- Web/mobile/chatbot clients
- Spectators
- Matchmaking / public lobbies (games are created and joined by invite/game code only)
- Ranking, stats, tournament play
- Real-time (websocket) updates — CLI will poll or rely on notification-triggered checks

## 3. High-Level Architecture

```
CLI  --->  API (API Gateway + Lambda)  --->  Domain/Rules Engine (pure library)
                    |
                    v
              DynamoDB (event log + materialized state)
                    |
                    v
        DynamoDB Streams -> Notification Lambda -> SES (email)
```

Key design decision: the rules engine is a pure, framework-free library (no AWS SDK calls inside it). It takes a state + a proposed move and returns either a new state or a validation error. The Lambda handlers are thin wrappers that load state, call the engine, persist the result, and return the player-specific view. This keeps the hard logic testable in isolation and reusable regardless of what infra sits around it.

Serverless (API Gateway + Lambda + DynamoDB) fits well here: traffic is bursty and tiny, state per game is small, and there's no always-on server to manage for a hobby-scale project.

## 4. Data Model

### 4.1 Storage approach: event log + materialized view

Each game is a DynamoDB partition. Rather than overwriting one JSON blob per move (which invites lost-update races and gives no history), store each action as an immutable, ordered event, and additionally cache the current derived state for fast reads.

Table: `Texas42` (single-table design)

| PK | SK | Item type |
|---|---|---|
| `GAME#<gameId>` | `META` | Game metadata: players, seat order, status, created_at, and rule config (enabled contracts, doubles-as-own-suit flag, marks-to-win, default 7) |
| `GAME#<gameId>` | `EVENT#<seq>` | One immutable event: bid, pass, trump declaration, domino play |
| `GAME#<gameId>` | `STATE` | Materialized current full state (server-side only — includes all hands), plus `version` for optimistic locking |
| `PLAYER#<playerId>` | `GAME#<gameId>` | Lookup: which games a player is in, and their seat/turn status (for "my games" queries and notification targeting) |

Event example:
```json
{
  "PK": "GAME#7f3a",
  "SK": "EVENT#0012",
  "type": "PLAY_DOMINO",
  "actor": "playerId-3",
  "payload": { "domino": [4, 1] },
  "timestamp": "2026-08-09T14:02:11Z"
}
```

Current state is derived by replaying events from the last snapshot (or from scratch — a full hand is at most ~35 events, replay is cheap). The `STATE` item is a snapshot/cache for reads, rebuilt on every write inside the same transaction that appends the event, using a DynamoDB `TransactWriteItems` call conditioned on `version` to prevent concurrent-write races.

### 4.2 Player-specific view

The full `STATE` item is never returned to a client directly. A `project(state, playerId)` function in the domain layer strips other players' hands and the undealt boneyard, and adds derived fields useful to a client (whose turn it is, legal moves for the requesting player if it's their turn, current trick, score history). All clients — CLI now, web/app/bot later — consume this projected view, so hidden-information rules live in exactly one place.

## 5. Domain / Rules Engine

Structured as a pure library, independent of AWS, with these components:

- **Domino & suit logic**: representation of the 28 tiles, suit-of-a-domino given trump (including doubles-as-trump variant), ranking within a suit/trump.
- **Bid state machine**: turn order for bidding, valid bid values (numeric 30–42, and mark-based contract bids), pass handling, re-bid rules, determining the winning bid and declarer.
- **Contract strategies**: a `Contract` interface with implementations for Standard, Nello, Plunge, Sevens, and Splash, each defining: who leads, whether/how a partner sits out or is dictated, trump-selection rules, legal-play rules, and scoring math for the hand. New contracts plug in without touching core trick logic — the engine holds a registry of known contracts keyed by name rather than a hardcoded switch.
- **Rule-variant flags**: doubles-as-own-suit, and which contracts are legal to bid, are treated as per-game configuration rather than global constants — set once at game creation (see `META` in section 4.1) and read by the bidding state machine and contract registry on every move. Adding a new variant later means adding a flag and a branch, not touching how existing games are scored or replayed.
- **Trick engine**: given current trick state and a proposed play, validates follow-suit legality and determines the trick winner.
- **Scoring**: count-domino values (5-5, 6-4 = 10; 5-0, 4-1, 3-2 = 5), trick points, comparison against the bid, mark accounting for game-to-N-marks.

This layer gets the heaviest test investment — property-based and table-driven unit tests covering suit-follow edge cases, each contract type, and scoring, since this is historically where domino-game implementations get subtly wrong.

## 6. API Surface (MVP)

REST-ish, one Lambda per action or a single router Lambda behind API Gateway:

- `POST /games` — create game, returns game code
- `POST /games/{id}/join` — join with a seat
- `GET /games/{id}` — get my current player-projected view
- `GET /players/me/games` — list games I'm in, with whose-turn-is-it flags
- `POST /games/{id}/bid` — submit a bid or pass
- `POST /games/{id}/contract` — declare trump / nello-partner-sitout / plunge trump-pick, as applicable after winning bid
- `POST /games/{id}/play` — play a domino

All mutating endpoints: validate via the domain engine, append event + update materialized state transactionally, return the caller's new projected view. Idempotency: each mutating request carries a client-generated request ID; duplicate submissions with the same ID are no-ops returning the prior result.

Auth for MVP: simplest workable option — a per-player API key issued at account creation, passed as a bearer token. (Revisit if a chatbot client needs OAuth-style flows later.)

## 7. CLI Client (MVP)

A thin client with no game logic of its own — it renders the projected view and posts moves.

Commands (rough):
```
t42 create-game --contracts nello,plunge,sevens,splash --doubles-trump --marks 7
t42 join <game-code> --seat 2
t42 status <game-code>            # show current view: your hand, trump, trick, whose turn
t42 bid <game-code> 32            # or: t42 bid <game-code> pass
t42 declare <game-code> trump=5   # after winning the bid
t42 play <game-code> 4-1
t42 games                          # list your active games, flag ones waiting on you
```

Domino notation: `a-b` (e.g., `6-4`, `5-5`). Status output renders hand, trump, current trick, and score in plain text/ASCII.

## 8. Notifications (MVP)

DynamoDB Streams on the `Texas42` table triggers a Lambda on new `PLAY_DOMINO`/`BID`/`PASS` events. It computes the new current player and sends an email via SES ("It's your turn in game 7f3a"). No push infra needed for a CLI-only MVP; this is also the natural extension point for SMS/push/chat-bot messages later, since the trigger and "whose turn now" logic don't change per client type.

## 9. Non-Functional Notes

- **Optimistic concurrency**: `version` field on `STATE`, conditional writes reject stale mutations (relevant mainly for double-submission, not real contention, given turn order).
- **Idempotency**: client request IDs as above.
- **Abandoned games**: out of scope for MVP logic-wise, but log last-activity timestamp per game now so a timeout/forfeit feature can be added without a data migration later.
- **Testing**: unit tests on the domain engine (highest priority), integration tests on the Lambda handlers against a local DynamoDB, and a scripted end-to-end 4-player CLI game as a smoke test.

## 10. Development Plan

**Phase 0 — Domain engine (no infra)**
Build the pure rules library: dominoes, suits/trump, bidding state machine, the four contract strategies, trick resolution, scoring. Full unit test suite. This phase produces a library that could, in principle, run a whole game in-memory with no network involved — useful as a milestone demo.

**Phase 1 — Persistence**
Design and implement the DynamoDB event log + materialized state + `project()` view function. Write the replay-from-events logic and snapshotting. Test against local DynamoDB (dynamodb-local or similar).

**Phase 2 — API layer**
Lambda handlers wrapping the domain engine and persistence layer, behind API Gateway. Wire up API keys. Contract tests for each endpoint (valid move, invalid move, out-of-turn, stale version).

**Phase 3 — CLI client**
Implement the command set above against the deployed API. Dogfood a full 4-player game manually (can be 4 terminal sessions or 4 test accounts).

**Phase 4 — Notifications**
DynamoDB Streams → Lambda → SES. Verify against real play across a delay (simulate the "hours between moves" case).

**Phase 5 — Hardening**
Abandoned-game handling, better CLI error messages/help, deploy scripting (SAM/CDK/Terraform — pick one), basic logging/observability.

Suggested order of effort: Phase 0 is the highest-risk, most logic-dense piece and should be done and well-tested before any AWS resources are provisioned — bugs there are cheapest to fix in isolation.

## 11. Notes for Future Clients

Because the domain engine and the player-projected view are both client-agnostic, adding a new client should mean:

- **Web app**: new frontend calling the same REST API; swap API-key auth for a session-based auth if desired; render the same projected-view JSON instead of CLI text.
- **Mobile app**: same API; add push notifications (APNs/FCM) as an alternative branch in the Phase 4 notification Lambda, keyed off a device token registered per player, no change to game logic.
- **Chatbot (Slack/Discord)**: same API; the bot posts the projected view as a formatted message and maps chat commands (`/t42 bid 32`) to the same endpoints. Turn notifications become bot DMs instead of email — again, just a new branch in the notification Lambda.

None of these require touching the domain engine, persistence layer, or API contract, provided the projected-view shape stays generic (plain data, not CLI-formatted text) from day one. Worth double-checking in Phase 1 that `project()` returns structured JSON rather than anything CLI-specific.

## 12. Open Questions

- Resolved: doubles-as-own-suit and which special contracts are enabled are per-game configuration, set at creation (see sections 4.1, 5). Six contracts ship in Phase 0: standard, nello, nello_low, sevens, plunge, splash.
- Resolved: contract rule variants.
  - **Nello / nello_low**: two separate registered contracts rather than one contract with a doubles-handling flag, since regional practice differs. `nello` (default, enabled by default): doubles form their own suit, ranked 6-6 high down to 0-0 low — fixed to this contract regardless of the game's `doubles_are_own_suit` flag. `nello_low`: doubles rank lowest in their number suit; off by default, enabled per game like splash. Both: declarer's partner sits out (hand is played 3-handed), declarer leads first, no trump, declarer's side must lose every trick or the bid is set.
  - **Plunge**: bidder holds 4+ of the 7 doubles, bids 4+ marks, and the bid only becomes live once the bidder's partner explicitly agrees ("do you want to plunge?"). If declined, no bid was placed and the proposer bids again on the same turn. The proposal and the response are both public — ordinary events on the game log, visible to every seat, whether accepted or declined; this is table information, not a private channel between partners. On a made bid, the bidder's partner (not the bidder) names trump and leads the first trick.
  - **Splash**: bidder holds 3+ of the 7 doubles, bids 2+ marks, no partner confirmation needed. Otherwise the same shape as plunge (partner names trump and leads). Off by default.
  - **Sevens**: no trump. The trick winner is whichever played tile has pip-sum closest to 7; ties go to whichever tied tile was played earliest (a later play must strictly beat the standing winner, not just match it).
  - **All-pass**: the dealer may not pass. If the other three seats have all passed, the dealer must place some legal bid — 30 points, or a mark bid for any contract they qualify for.
- Resolved: marks-to-win is configurable per game, defaulting to 7.
- Player identity/account model: email-based accounts, or something lighter (just a display name + secret game-join code) for MVP?
