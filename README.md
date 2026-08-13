# Texas 42 Online

A server-authoritative, asynchronous implementation of [Texas 42](https://en.wikipedia.org/wiki/42_(dominoes)):
partnership domino trick-taking with nello, plunge, sevens and splash. Games are played over
minutes or hours rather than in real time. See [DESIGN.md](DESIGN.md) for the architecture and
[ROADMAP.md](ROADMAP.md) for the phase-by-phase breakdown.

## Status

Phases 0 through 2 are complete. There is a pure rules engine covering all six contracts, durable
storage in DynamoDB with the event log as the source of truth, and an HTTP API over both.

- **Phase 0, rules engine.** Dealing, the full auction (including plunge confirmation and the
  dealer-must-bid rule), all six contracts, trick resolution and scoring, with a whole game
  runnable in memory.
- **Phase 0.5, house rules.** Every rule variant is per-game data on one validated `HouseRules`
  value, including each contract's own bid entry bar and the declared-lead privilege.
- **Phase 1, persistence.** Event log plus a materialized state item, optimistic concurrency,
  idempotent writes, replay that reruns real `apply_move` calls rather than reimplementing them,
  and the player-specific projection.
- **Phase 2, API.** FastAPI behind a Mangum adapter: accounts with per-device bearer tokens, a
  lobby, and the move endpoints. A full 4-player game runs signup to game-over over HTTP.

Next: **Phase 2.7**, tables - saved house-rule sets, invites by username, public or invite-only
tables, and a browse of open ones. It goes ahead of **Phase 3**, the CLI client, so the command set
is written once against the finished surface. Nothing is deployed yet - the API runs locally against
DynamoDB Local, and provisioning is an open question recorded in ROADMAP.md.

## Layout

```
src/t42/engine/     pure rules library: no I/O, no AWS, no dependency on the layers below
src/t42/storage/    DynamoDB event log, materialized state, lobby and accounts
src/t42/api/        FastAPI app and its Lambda entry point
src/t42/cli/        thin command-line client  (Phase 3)
tests/
```

The engine is the only place game rules live, and every client type consumes the same projected
view, so hidden-information rules exist in exactly one place. See the invariants in
[CLAUDE.md](CLAUDE.md) before making structural changes.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 matches the AWS Lambda runtime and is
fetched automatically.

```bash
uv sync --extra dev            # create the venv and install dev tooling
uv run pytest                  # tests (fast; excludes the Docker-backed integration suite)
uv run pytest -m integration   # integration tests against real DynamoDB Local (needs Docker)
uv run mypy                    # type check (strict, over src and tests)
uv run ruff check .            # lint
uv run ruff format .           # format
```

CI runs all of the above, with the integration suite as its own step.

## Running the API locally

```bash
docker run -d --name t42-ddb -p 8123:8000 amazon/dynamodb-local:latest

export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1
export T42_TABLE_NAME=Texas42 T42_DYNAMODB_ENDPOINT=http://localhost:8123

uv run python -c "
import boto3
boto3.resource('dynamodb', endpoint_url='http://localhost:8123').create_table(
    TableName='Texas42',
    KeySchema=[{'AttributeName':'PK','KeyType':'HASH'},{'AttributeName':'SK','KeyType':'RANGE'}],
    AttributeDefinitions=[{'AttributeName':'PK','AttributeType':'S'},
                          {'AttributeName':'SK','AttributeType':'S'}],
    BillingMode='PAY_PER_REQUEST').wait_until_exists()"

uv run uvicorn t42.api.app:app --reload --port 8765
```

Interactive API docs are then at `http://localhost:8765/docs`. Register a player, create a game,
and share the six-character game code with three others to fill the seats:

```bash
curl -X POST localhost:8765/players -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"correct-horse-battery"}'

curl -X POST localhost:8765/games -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" -d '{"seat":0}'
```
