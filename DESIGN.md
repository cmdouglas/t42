# Texas 42 Online — Design Document & MVP Development Plan

## 1. Goals

Build a server-authoritative, asynchronous implementation of Texas 42 (partnership domino trick-taking, with nello, plunge, and sevens as special contracts) that multiple client types can share. The MVP ships a command-line client only; the architecture should make adding a web app, mobile app, or chatbot client later a matter of writing a thin client against an existing API, not rewriting game logic.

Design priorities, in order: correctness of rules, no leakage of hidden information (hands, remaining dominoes) to the wrong player, and support for play spread across minutes or hours. Real-time performance is not a concern.

## 2. Scope for MVP

In scope:
- 4-player, fixed-partnership games (2v2, partners seated across from each other)
- Standard bidding (30–42, points-based) plus mark-based special contracts: nello, plunge, sevens
- Configurable rule variants selected at game creation: which special contracts are enabled (nello, plunge, sevens, splash, ...) and whether doubles count as their own suit
- Saved house-rule sets a player can name, edit, and apply to tables they create (section 5.1)
- Tables created either public or invite-only, with invites addressed by username (section 6.2)
- A browsable list of public tables with seats free
- Server-side move validation
- CLI client for creating/joining games, bidding, and playing
- Email notification when it's a player's turn
- Single region, single small DynamoDB table, no horizontal scaling concerns

Out of scope for MVP (noted for later):
- Web/mobile/chatbot clients
- Spectators
- Skill-based matchmaking: the open-table list above is a plain newest-first browse, not a matcher
- Ranking, stats, tournament play
- Bot players filling empty seats - designed in section 13, deliberately built last
- Real-time (websocket) updates - CLI will poll or rely on notification-triggered checks

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
| `GAME#<gameId>` | `META` | Game metadata: seats (each with player id and username), `status` of `WAITING`/`ACTIVE`/`COMPLETE`, `visibility` of `public`/`invite_only` (section 6.2), created_at, last_activity_at, and the game's house rules (enabled contracts, per-contract options, doubles-as-own-suit flag, marks-to-win, default 7 - see section 5.1) |
| `GAME#<gameId>` | `EVENT#<seq>` | One immutable event: bid, pass, trump declaration, domino play |
| `GAME#<gameId>` | `STATE` | Materialized current full state (server-side only — includes all hands), plus `version` for optimistic locking. Does not exist until the game is `ACTIVE` |
| `PLAYER#<playerId>` | `GAME#<gameId>` | Lookup: which games a player is in, and their seat/turn/game status (for "my games" queries and notification targeting) |
| `GAME#<gameId>` | `REQUEST#<requestId>` | Idempotency marker for a mutating request, storing the version it produced - a duplicate submission with the same client-generated request ID is a no-op returning the recorded version (section 9) |
| `PLAYER#<playerId>` | `PROFILE` | Username, contact channels, created_at (section 6.1) |
| `USERNAME#<lowercased>` | `PLAYER` | Username uniqueness reservation, claimed by conditional put |
| `TOKEN#<sha256(token)>` | `TOKEN` | Auth token: player id, device label, created_at, last_used_at, expires_at |
| `PLAYER#<playerId>` | `TOKEN#<sha256>` | Reverse lookup, so a player can list and revoke their devices |
| `PLAYER#<playerId>` | `RULESET#<ruleSetId>` | A saved house-rule set: display name, the encoded `HouseRules`, created_at, updated_at (section 5.1) |
| `GAME#<gameId>` | `INVITE#<playerId>` | An invite, from the game's side: read as a single `GetItem` when somebody tries to take a seat |
| `PLAYER#<playerId>` | `INVITE#<gameId>` | The same invite from the invitee's side, so "my pending invites" is one Query |

The `PLAYER#<playerId>` partition now carries five SK prefixes - `PROFILE`, `GAME#`, `TOKEN#`,
`INVITE#` and `RULESET#` - each list read being a `begins_with` query that cannot see the others.
The two invite items are one fact stored twice, once per access path, so they are written and
deleted together in a `TransactWriteItems` call: a half-invite would either be unusable or
invisible, and neither is a state worth being able to reach.

A game's id doubles as its join code (section 2): six characters from an alphabet omitting `I`,
`L`, `O`, `U`, `0` and `1`, so it survives being read aloud or typed from a phone screen. No
separate code-to-game lookup is needed, and a collision surfaces as the same conditional-put
failure that rejects a duplicate game id.

**Game lifecycle.** A game is created `WAITING`, and either `public` or `invite_only`, with only
its creator seated; players join seats until it is full. The join that fills the fourth seat deals
the first hand and flips `status` to `ACTIVE` in one transaction, conditioned on `status` still
being `WAITING` so two simultaneous fourth joins cannot deal twice. This lives entirely in the
storage layer: the rules engine has no notion of a partially seated game, and `new_game` still
takes four seats and deals.

**Open-games index.** Browsing public tables (section 6.2) is the one read that is not addressed by
a key the caller already holds, so it gets the table's only secondary index: `OpenGames`, on
`GSI1PK` (hash) and `GSI1SK` (range), projecting `ALL` - `META` is small, and projecting everything
means a browse row needs no follow-up read.

The index is **sparse**. A `META` item carries `GSI1PK = "OPEN"` and `GSI1SK = <created_at>` only
while the game is public *and* `WAITING`; every other item in the table omits both attributes and is
therefore absent from the index entirely. An invite-only game never writes them. A public game drops
out when it is dealt, because `start_game` removes both attributes in the same conditional update
that flips `status` to `ACTIVE` - and that update is the only way a game can leave `WAITING`, so
there is no second place to remember. Browsing is then one query on `GSI1PK = "OPEN"`, descending by
`GSI1SK`, giving newest-first for free from an ISO-8601 timestamp's lexicographic order.

Two consequences worth writing down. The single `"OPEN"` partition is a hot key, and a real limit at
some scale well past this project's; the escape is to shard it (`OPEN#<n>` for a small fixed `n`,
read scatter-gather), which needs no data migration, since the index is derived from `META` and
DynamoDB rebuilds it. And a GSI is **eventually consistent**: a table created a moment ago may not
appear in the next browse. That is acceptable - the creator has the join code and does not need the
list - but it does mean an integration test has to poll rather than assert immediately, and that
moto, being strongly consistent, will never reproduce the behaviour that makes the polling
necessary.

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
- **Rule-variant flags**: every rule choice that varies between tables - which contracts are legal to bid, the terms each may be bid on, doubles-as-own-suit, marks-to-win - is per-game configuration rather than a global constant, set once at game creation (see `META` in section 4.1) and read by the bidding state machine and contract registry on every move. Section 5.1 defines the model.
- **Trick engine**: given current trick state and a proposed play, validates follow-suit legality and determines the trick winner.
- **Scoring**: count-domino values (5-5, 6-4 = 10; 5-0, 4-1, 3-2 = 5), trick points, comparison against the bid, mark accounting for game-to-N-marks.

This layer gets the heaviest test investment — property-based and table-driven unit tests covering suit-follow edge cases, each contract type, and scoring, since this is historically where domino-game implementations get subtly wrong.

### 5.1 House rules

A *house-rule set* is the complete set of rule choices a table plays under: which contracts are available, the terms each may be bid on, and how the game is scored. It is fixed when the game is created, stored on the `META` item, and threaded through every engine call as an argument - never read from module state. Two games created under different house rules must score and replay correctly side by side in the same process.

**Shape.** One frozen `HouseRules` value (`t42/engine/house_rules.py`) carries:

| Field | Meaning |
|---|---|
| `enabled_contracts` | Which registered contracts may be bid this game. `standard` cannot be disabled. |
| `contract_options` | Per-contract terms: `Mapping[str, Mapping[str, OptionValue]]`, where `OptionValue = int \| bool \| str`. |
| `doubles_are_own_suit` | Whether doubles form a seventh suit rather than sitting in their number suit. |
| `allow_declared_lead` | Whether a leader may name which end of their tile is the suit led: `never` (default), `first_trick`, `always`. See section 5.2. |
| `marks_to_win` | Game length, default 7. |

`contract_options` is plain data, so the Phase 1 codec encodes it with no special cases and a replayed game gets byte-identical rules.

**Contracts declare their own options.** The core config type never names a specific contract - that would undo the registry. Instead the `Contract` protocol gains:

- `option_defaults() -> Mapping[str, OptionValue]` - the option keys this contract accepts, with the values used when the house does not override them.
- `validate_options(options, rules) -> None` - the contract's own checks on the merged result.

A contract reads its effective terms through `HouseRules.options_for(name)`, which merges the game's overrides over that contract's defaults. Because `option_defaults()` enumerates the accepted keys, an unrecognised key is an error, which gives typo detection with no schema language.

Example: plunge and splash differ only in their entry bar and whether the partner must confirm, so those minimums are options rather than facts about the contract class:

```
HouseRules(
    enabled_contracts=frozenset({"standard", "nello", "plunge", "splash"}),
    contract_options={
        "plunge": {"minimum_doubles": 5, "minimum_marks": 4},  # a stricter-than-usual table
        "splash": {"minimum_doubles": 3, "minimum_marks": 2},  # the usual bar
    },
)
```

**Validation is two layers**, so `house_rules.py` stays dependency-free and importable without the registry:

1. `HouseRules.__post_init__` - structural checks that need no registry: `marks_to_win >= 1`, `standard` present in `enabled_contracts`, option values of the right type.
2. `contracts.validate_house_rules(rules)` - registry-aware checks, called from `new_game` so an invalid rule set can never produce a game: every named contract is registered, every contract given options is actually enabled, every option key is one that contract declares, and each contract's own `validate_options` passes.

**What "makes sense" means.** A house-rule set is rejected unless it clears three tiers:

1. **Structural** - names resolve, the required contract is present, values are the right type and in range.
2. **Satisfiable** - every enabled contract must be biddable under the rest of the rule set. A doubles minimum above 7 can never be met (there are only 7 doubles); a mark minimum above the 7-mark bid ceiling can never be bid. Enabling a contract nobody can ever bid is a bug in the rule set, not a quirk of it.
3. **Coherent** - choices must not contradict each other across contracts. This tier is deliberately thin while entry bars are the only options, and it should stay thin: a rule set that is merely unusual is the table's business, and only a genuine self-contradiction is rejected. The one check today: plunge is by definition the heavier of the two doubles contracts, so if both are enabled, plunge's bar must be at least as hard as splash's on both axes. A game where splash demands more doubles or more marks than plunge has the two contracts inverted, and the names no longer mean what the rest of the design says they mean. This check lives inside the plunge and splash contracts, which receive the whole `HouseRules` in `validate_options`, so no core module learns their names.

   Note what is *not* checked. Plunge and splash score identically and plunge additionally needs the partner's confirmation, so at the default bars (plunge 4 doubles / 4 marks, splash 3 / 2) any hand that could plunge could instead splash, with no confirmation step and at the same reward. Plunge is therefore weakly dominated by splash whenever both are enabled. That is a property of the game, not an error in the rule set - most tables enable one or the other - so the validator records it in neither direction and lets the table play as it likes.

**Flag or new contract?** Both kinds of variant exist, and the line between them is *scope*, not size:

- A **game-wide** mechanic, applying uniformly to every contract the game enables, is a flag on `HouseRules`. `doubles_are_own_suit` is one: it changes suit membership, ranking and what may be trump, for every contract at once. Declared leads (section 5.2) is another.
- A **contract-specific** behavioural difference is a new registered contract, not a flag. This is exactly why `nello_low` is its own contract rather than a `nello` option (see section 12): only nello's own trick resolution changes, so the difference belongs behind the `Contract` protocol where the rest of the engine never sees it.

A contract may narrow a game-wide flag for itself through `contract_options` (a table might allow declared leads generally but not under nello), but never widen one past what the game allows. Narrowing is a table's business; widening is a contradiction, and the validator rejects it.

**Non-goal.** `HouseRules` selects among registered contracts, sets their numeric terms, and switches the game-wide mechanics enumerated above. It does not let a game invent a contract, and it is not an extension language: every option is a named field or a declared per-contract key that some engine module reads on purpose. Variants not yet modelled (the set penalty, the mark value of a made point bid, the bid floor and ceiling, the all-pass rule) are fixed for now; the point of the mechanism is that adding one later is adding an option, not another refactor.

**Saved rule sets.** A group that plays the same way every week should not retype its rules every
table, so a player may keep named `HouseRules` values on their account (`RULESET#` in section 4.1)
and name one when creating a game. This is a convenience layer on top of the model above and
changes nothing about it: a saved set is exactly a `HouseRules`, stored with the same encoder the
`META` item uses.

Three properties are load-bearing:

- **Applying a set copies it.** `META.config` already holds the game's own encoded rules, so a table
  created from a saved set is unaffected by later edits to that set - a game's rules cannot change
  under the players mid-game, and a replay of an old game reproduces the rules it was actually
  played under. This falls out of the storage model rather than needing enforcement, but it is a
  guarantee and should be tested as one.
- **A set is validated when saved**, through the same `contracts.validate_house_rules` that guards
  game creation. The reasoning matches the lobby's: an incoherent set that only failed at the table
  is a trap somebody saved weeks earlier and has since forgotten the shape of.
- **The id is opaque and the display name is not unique.** Same argument as `PlayerId` (section 12):
  keying on the name would make renaming a delete-and-recreate. A player keeps a handful of these,
  so duplicate names are a cosmetic matter for the client to warn about, not a correctness one worth
  a uniqueness-reservation item.

Sets are private to the player who owns them; they live under that player's partition, so a rule-set
id belonging to somebody else is simply not found, and access control needs no check of its own.
Server-provided presets ("tournament", "all contracts") would be purely additive - another source
`POST /games` can resolve an id against - and are not part of the MVP.

### 5.2 Declared leads

A house rule some tables play: **the leader may name which of a tile's two ends is the suit led**, instead of the default rule that a non-trump lead calls for its higher end. Leading `3-2`, the leader may call it the three of twos rather than the two of threes, and everyone follows twos.

The option is three-valued rather than a boolean, because tables differ on how far the privilege extends:

| `allow_declared_lead` | Meaning |
|---|---|
| `"never"` (default) | The higher end names the suit, always. Current engine behaviour. |
| `"first_trick"` | The leader may declare on the first trick of each hand only. |
| `"always"` | The leader may declare on any trick they lead. |

Declaring is never compulsory under any setting: a lead with no declaration falls back to the higher-end rule.

**The model change this forces.** Today the led suit is *derived*, recomputed from the opening tile by `suits.led_suit()` wherever it is needed. Under this rule it becomes a *decision*, and a decision that cannot be reconstructed from the tiles alone. So the led suit becomes recorded state:

- `Trick` gains `declared_suit: Suit | None`, `None` meaning "apply the default rule".
- One helper, `suit_led(trick, trump, rules)`, returns the declaration if present and falls back to `led_suit()` otherwise. It replaces both existing `led_suit()` call sites, which sit together in `trick_rules.py` (follow-suit legality, and the trick winner). Every contract already routes through those two functions, so no contract changes.
- `PlayDomino` and `DominoPlayed` gain the declared suit. It **must** ride on the event: a log that recorded only the tile could not be replayed, since the suit led is no longer a function of the tile. This is the same argument that puts the plunge confirmation on the log.

Ranking needs no change at all. `rank_in_suit` already ranks a tile by its *other* end relative to whichever suit is asked about, so `3-2` is the two of threes or the three of twos depending only on the suit passed in.

**Trump does not become negotiable.** A tile with a trump end is a trump tile, and leading it leads trump. The declaration chooses between the two ends only when neither is trump, so a lead can never be laundered out of the trump suit. The alternative, letting the leader call `3-2` a two while threes are trump, would make trump membership a property of the trick rather than of the tile plus the hand's trump, and the rule that "a trump follows trump and nothing else" would stop having a well-defined meaning for the other three players.

**Doubles offer no choice**, under either setting of `doubles_are_own_suit`: a double belongs to a single number suit, or to the doubles suit alone. Nothing to declare.

**Scope across contracts.** The flag is game-wide and applies to every enabled contract, with two consequences worth stating. Under nello and sevens there is no trump, so every non-double a leader holds has two live ends and the privilege is at its strongest; a table that wants declared leads in standard play but not under nello narrows it there through `contract_options` (see section 5.1). Under sevens the declaration changes what the other seats may legally play without changing who wins the trick, since the sevens winner is decided by pip distance and ignores suit entirely.

**Hidden information is unaffected.** The declaration is announced at the table, rides on the public `DominoPlayed` event, and appears in the current and completed tricks that `project()` already exposes. No new gate, and nothing for `project()` to filter.

## 6. API Surface (MVP)

REST-ish, a single FastAPI app behind one Lambda (via Mangum) and API Gateway:

- `POST /players` - register: username + password, returns the player id and a first token
- `POST /sessions` - sign in on a device, returns a bearer token
- `DELETE /sessions/current` - sign out, revoking this device's token
- `GET /players/me` - own profile, contact channels, and active devices
- `POST /players/me/rule-sets` - save a named house-rule set
- `GET /players/me/rule-sets` - list my saved sets
- `GET /players/me/rule-sets/{ruleSetId}` - read one
- `PUT /players/me/rule-sets/{ruleSetId}` - replace its name and rules
- `DELETE /players/me/rule-sets/{ruleSetId}` - delete it
- `POST /games` - create game, returns the game code; creator takes a seat. Takes either an inline house-rule body or a saved `ruleSetId`, and a `visibility` of `public` (default) or `invite_only`
- `POST /games/{id}/join` - join with a seat
- `GET /games/{id}` - get my current player-projected view
- `GET /games/open` - browse public tables with seats free, newest first
- `POST /games/{id}/invites` - invite a player by username; any seated player may
- `DELETE /games/{id}/invites/{playerId}` - revoke an invite (a seated player) or decline one (the invitee)
- `GET /players/me/invites` - my pending invites
- `GET /players/me/games` - list games I'm in, with whose-turn-is-it flags
- `POST /games/{id}/bid` - submit a bid, a pass, or a confirmation of a pending bid
- `POST /games/{id}/contract` - declare trump / nello-partner-sitout / plunge trump-pick, as applicable after winning bid
- `POST /games/{id}/play` - play a domino

All mutating endpoints: validate via the domain engine, append event + update materialized state transactionally, return the caller's new projected view. Idempotency: each mutating request carries a client-generated request ID in an `Idempotency-Key` header; duplicate submissions with the same ID are no-ops returning the prior result.

The plunge confirmation has no endpoint of its own. It is an auction move, so it rides on `/bid` as one variant of a body discriminated on `kind` (`BID` / `PASS` / `CONFIRM_BID`), which is exactly the engine's move alphabet for that phase.

The client never sends a version. The server reads the current one, applies the move and writes conditionally in the same request, so optimistic-concurrency bookkeeping stays server-side and `version` never appears on the wire. A lost race surfaces as `409`, with no automatic retry — real contention is impossible in a turn-based game, since a concurrent submission by another player is rejected as out-of-turn first and a resubmission by the same player is absorbed by its idempotency key.

### 6.1 Authentication

**Bearer tokens, one per device, revocable individually.** A request proves identity with
`Authorization: Bearer <token>`; the token resolves to a player id through a single `GetItem` on
its hash. This is the durable half of the decision, and it is independent of how tokens are
minted: adding a magic link or an OIDC flow later means adding a way to mint a token, not changing
the handlers, the game storage, or any client's request path.

Tokens do not expire and are revoked explicitly, matching how a CLI credential file behaves in
practice and suiting play spread over days. A player accumulates one token per device, so signing
in on a phone leaves a desktop session alone and losing a device revokes exactly one credential.

Minting for MVP is **username + password**, hashed with `hashlib.scrypt` from the standard
library. Passwords get a deliberately slow hash; tokens, being high-entropy random values, get
sha256, which is the appropriate choice for each. Nothing here needs a dependency or an external
service, so the whole auth path is testable offline.

Two things are deliberately deferred rather than forgotten. **Password reset and email
verification** need a send channel, which does not exist until Phase 4's SES work, so they land
there. **Login rate limiting** is Phase 5; until then the floor is scrypt's cost plus error
messages that do not distinguish an unknown username from a wrong password.

The threat model justifies that floor. An attacker who impersonates a player can see a hand and
play moves — grief, not fraud. There is no money and no meaningful personal data beyond a display
name and whatever contact channel a player volunteers. Hidden-information leakage is still design
priority #2, so this is not nothing, but every option considered clears that bar comfortably; the
differences between them are about recovery and friction rather than strength.

### 6.2 Table visibility and invites

Until now the join code has been the whole of a table's access control: holding it is permission to
sit down, and a table nobody told you about is unreachable. That collapses two separate wishes - "I
want to play with these three people" and "I want a game, whoever shows up" - into one mechanism
that serves neither well. So a table declares which it is at creation:

| `visibility` | Who may take a seat | Listed in `GET /games/open` |
|---|---|---|
| `public` (default) | Anyone with the code | Yes, while `WAITING` with a seat free |
| `invite_only` | Only an invited player | Never |

`public` is the default because it is exactly today's behaviour, so nothing that exists changes
meaning.

**An invite is a permission grant, not a seat reservation.** It records that a player may join, and
they still pick whichever seat is open when they arrive. The alternative - an invite naming and
holding a seat - was rejected because it adds a second reason a seat can be unavailable, and seat
claiming is the one place in the lobby where concurrency actually bites (section 4.1): keeping it a
single conditional update with exactly one way to fail is worth more than letting a host arrange
partnerships in advance. A host who cares about seating can say so out of band.

**Any seated player may invite.** There is no host role, and the seats map has no creator field to
add one to. A casual game fills up by everybody at the table pulling in whoever they know, which is
also what makes the missing-creator concept a feature rather than an omission.

**The check belongs in the storage layer's seat claim**, next to the existing seat-taken,
already-seated and not-joinable checks, rather than in a handler. Storage is the single authority on
who may sit down; a second gate above it is a second thing to keep in agreement with the first.

The check is a read-then-write, deliberately. Its one window is an invite revoked in the seconds
between the read and the claim, which lets one join through that should have been refused. Closing
it means promoting the claim to a transaction with a `ConditionCheck` on the invite item, which
costs the precise `ConditionalCheckFailedException` attribution the claim currently uses to tell the
caller *which way* they lost - seat taken, or game already dealt. Against the threat model in
section 6.1 that is a bad trade: the failure is one unwanted player at a casual game, and the
remedy is to not invite them again.

A consumed invite is deleted when the join succeeds, so it stops appearing in the invitee's pending
list. An invite to a game that fills up without them is left in place and filtered on read, since
the alternative is a fan-out delete inside the deal transaction to save a row nobody is looking at.

**Reading a table you are not seated at.** An invitee needs to see the house rules and who is
already there before deciding, so `GET /games/{id}` widens from strictly-seated to three cases:

| Caller | Response |
|---|---|
| Seated | Unchanged: lobby fields plus their projected `view` |
| Invited, or the table is public and `WAITING` | Lobby fields only, `view: null` |
| Anyone else | `403` |

The rule this establishes is that **the view is projected only for a seated caller**, replacing the
current test of whether the game has been dealt. A non-seated caller never reaches `project()` at
all, which keeps section 4.2's single gate exactly as narrow as it was while widening what the lobby
around it will show.

## 7. CLI Client (MVP)

A thin client with no game logic of its own — it renders the projected view and posts moves.

Commands (rough):
```
t42 create-game --contracts nello,plunge,sevens,splash --doubles-trump --marks 7 \
      --set plunge.minimum_doubles=5      # per-contract house-rule options, section 5.1
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

**Phase 2.7 - Tables**
Saved rule sets, invite-by-username, public/invite-only visibility, and the open-games browse (sections 5.1, 6.2). Before the CLI on purpose: these are all table-setup surface, and the CLI's command set should be written once against the finished shape rather than grown into it.

**Phase 3 — CLI client**
Implement the command set above against the deployed API, including the Phase 2.7 commands. Dogfood a full 4-player game manually (can be 4 terminal sessions or 4 test accounts).

**Phase 4 — Notifications**
DynamoDB Streams → Lambda → SES. Verify against real play across a delay (simulate the "hours between moves" case).

**Phase 5 — Hardening**
Abandoned-game handling, better CLI error messages/help, deploy scripting (SAM/CDK/Terraform — pick one), basic logging/observability.

**Phase 6 - Bot players**
Section 13. Last on purpose: it is the only feature that needs everything else working first, since a bot is a client of the finished API.

Suggested order of effort: Phase 0 is the highest-risk, most logic-dense piece and should be done and well-tested before any AWS resources are provisioned — bugs there are cheapest to fix in isolation.

## 11. Notes for Future Clients

Because the domain engine and the player-projected view are both client-agnostic, adding a new client should mean:

- **Web app**: new frontend calling the same REST API; swap API-key auth for a session-based auth if desired; render the same projected-view JSON instead of CLI text.
- **Mobile app**: same API; add push notifications (APNs/FCM) as an alternative branch in the Phase 4 notification Lambda, keyed off a device token registered per player, no change to game logic.
- **Chatbot (Slack/Discord)**: same API; the bot posts the projected view as a formatted message and maps chat commands (`/t42 bid 32`) to the same endpoints. Turn notifications become bot DMs instead of email — again, just a new branch in the notification Lambda.

None of these require touching the domain engine, persistence layer, or API contract, provided the projected-view shape stays generic (plain data, not CLI-formatted text) from day one. Worth double-checking in Phase 1 that `project()` returns structured JSON rather than anything CLI-specific.

## 12. Open Questions

- Resolved: doubles-as-own-suit and which special contracts are enabled are per-game configuration, set at creation (see sections 4.1, 5.1). Six contracts ship in Phase 0: standard, nello, nello_low, sevens, plunge, splash.
- Resolved: contract rule variants. The doubles and marks minimums below are the **defaults** a table gets when it says nothing; each is a per-contract house-rule option a game may override at creation (section 5.1). Everything else below is intrinsic to the contract and not configurable.
  - **Nello / nello_low**: two separate registered contracts rather than one contract with a doubles-handling flag, since regional practice differs. `nello` (default, enabled by default): doubles form their own suit, ranked 6-6 high down to 0-0 low — fixed to this contract regardless of the game's `doubles_are_own_suit` flag. `nello_low`: doubles rank lowest in their number suit; off by default, enabled per game like splash. Both: declarer's partner sits out (hand is played 3-handed), declarer leads first, no trump, declarer's side must lose every trick or the bid is set.
  - **Plunge**: bidder holds 4+ of the 7 doubles, bids 4+ marks, and the bid only becomes live once the bidder's partner explicitly agrees ("do you want to plunge?"). If declined, no bid was placed and the proposer bids again on the same turn. The proposal and the response are both public — ordinary events on the game log, visible to every seat, whether accepted or declined; this is table information, not a private channel between partners. On a made bid, the bidder's partner (not the bidder) names trump and leads the first trick.
  - **Splash**: bidder holds 3+ of the 7 doubles, bids 2+ marks, no partner confirmation needed. Otherwise the same shape as plunge (partner names trump and leads). Off by default.
  - **Sevens**: no trump. The trick winner is whichever played tile has pip-sum closest to 7; ties go to whichever tied tile was played earliest (a later play must strictly beat the standing winner, not just match it).
  - **All-pass**: the dealer may not pass. If the other three seats have all passed, the dealer must place some legal bid — 30 points, or a mark bid for any contract they qualify for.
- Resolved: enabling both `nello` and `nello_low` in the same game is legal, not a rule-set contradiction. They are two separately registered contracts, so a bidder names the doubles ranking they want by naming the contract; nothing about the game state is ambiguous. A table that plays only one way simply enables only one.
- Resolved: marks-to-win is configurable per game, defaulting to 7.
- Resolved: player identity/account model. A player is an **opaque server-generated id** with a
  **unique username** and a **list of contact channels**, authenticated by username + password
  minting per-device bearer tokens (section 6.1). Three consequences worth stating, since each
  rules out a lighter option that was on the table:
  - The id is opaque rather than being the username, so usernames stay renameable and never get
    embedded in the event log, which is immutable by invariant 6.
  - Contacts are a list of `{kind, address, verified}` channels rather than a bare `email` field.
    Phase 4's notification Lambda branches on `kind`, so adding SMS or a chat DM is a new branch
    rather than a data migration — the same argument section 9 makes for `last_activity_at`.
    Nothing requires a player to have an email at all.
  - A bare API key shown once at signup was rejected: moving it to a second device means
    copy-pasting a secret by hand, and losing it strands the account with no recovery path, since
    there is no verified channel to recover through.
- Resolved: **an invite is a permission grant, not a seat reservation**, and any seated player may
  send one (section 6.2). The reservation model was rejected for making seat availability depend on
  two facts instead of one, in the single lobby operation where concurrency actually bites. There is
  no host role: the seats map has no creator field, and a casual game filling up by everyone pulling
  in whoever they know is the behaviour wanted anyway.
- Resolved: **`public` means browsable, not merely code-joinable** (sections 4.1, 6.2). A public
  table appears in `GET /games/open` through the sparse `OpenGames` GSI - the table's first
  secondary index - and leaves it when `start_game` removes the index attributes as it deals. The
  weaker reading, where public and invite-only differ only in whether the seat claim checks for an
  invite, was rejected as leaving no way to find a game at all: the code would still have to reach
  you by some channel outside the system. Accepted costs: one hot index partition, shardable later
  without a migration, and eventual consistency on the browse.
- Resolved: **saved rule sets are per-player, opaque-id, and copied on use** (section 5.1). Keying
  them by display name would make a rename a delete-and-recreate; referencing rather than copying
  would let a table's rules change under the players mid-game and would make an old game's log
  unreplayable against its own rules. Server-provided presets are additive and deferred.
- Resolved: **bot players are a client of the public API, not a server-side special case**
  (section 13), and are sequenced last.

## 13. Bot Players (post-MVP)

Four-handed partnership games need four people, and asynchronous play means a table can stall for
days on one absent seat. Bots that fill empty seats are the eventual answer. Nothing here is built;
this section fixes the shape so the decisions that constrain earlier phases are already made.

**A bot is an ordinary player account.** A `PROFILE` item with `is_bot: true`, a player id, a
username, and a token - seated through the same join path as anybody else. Neither the rules engine,
the lobby, nor the repository learns that bots exist, and no seat is a special kind of seat. The
flag exists so clients can render "Bot Bertha" honestly and so a table can decline bots if it wants
to; nothing in the game logic branches on it.

**A bot plays through the public HTTP API**, authenticating with its own bearer token and acting on
exactly the `project()` output every other client gets. This is the load-bearing decision and the
reason bots are cheap. An in-process bot reading `GameState` directly would be a second consumer of
hidden information sitting next to the single gate of section 4.2 - and one that, by construction,
can see every hand. Keeping the bot outside means it *cannot* cheat, and that this is true by the
same argument that makes it true of the CLI, not by a separate audit.

The consequence worth noticing is that the projected view must be sufficient to play from. It
already is: `legal_moves` is on every view, so the first policy - pick uniformly at random from the
legal moves - is a few lines, and the interface is `choose(view) -> move`. That is the same shape as
the `choose` hook the API test driver already uses to play whole games, so the first bot is
substantially a promotion of test-harness code.

**Driving it.** Every write already stamps `is_my_turn` onto the four `PLAYER#` items (section 4.1),
so a DynamoDB Streams reaction on that flip is the natural trigger, and Phase 4 introduces Streams
for notifications regardless - a bot's turn and a human's turn notification are the same event with
different deliveries. Polling `GET /players/me/games` is the fallback and is adequate for a game
measured in hours.

**Left open**, to be settled when the phase is picked up: how a bot gets seated. An explicit "add a
bot" call from a seated player is the simplest, and auto-filling a table that has sat idle past some
`last_activity_at` threshold is the more useful; they are not exclusive, and the second overlaps
Phase 5's abandoned-game work.
