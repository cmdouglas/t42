"""The HTTP surface (ROADMAP.md 2.4, DESIGN.md §6).

Every handler here is thin by design: it authenticates, converts a request body into an engine
``Move``, and hands off. All the deciding happens below it - the engine says whether a move is
legal, the repository says whether the write won its race, and ``project`` says what the caller
may see. Nothing in this module reimplements any of that, and no handler reaches into
``GameState`` to build a response.

``_submit`` is the whole of it for the three move endpoints, and is worth reading first.
"""

from __future__ import annotations

from random import Random
from typing import Any

from fastapi import FastAPI, status
from mypy_boto3_dynamodb.service_resource import Table

from t42.engine.errors import RulesError
from t42.engine.game import apply_move
from t42.engine.moves import Move
from t42.engine.projection import project
from t42.engine.state import GameId, PlayerId
from t42.storage.accounts import (
    authenticate,
    create_player,
    get_player,
    hash_token,
    issue_token,
    list_tokens,
    revoke_token,
)
from t42.storage.errors import GameAlreadyExists, GameNotFound, VersionConflict
from t42.storage.events import events_for_move
from t42.storage.lobby import (
    Lobby,
    create_pending_game,
    get_lobby,
    join_seat,
    list_games_for_player,
    new_game_code,
)
from t42.storage.repository import GameStatus, append, find_request, get_state

from .deps import BearerToken, CurrentPlayer, IdempotencyKey, TableDep
from .errors import install_error_handlers, not_a_player, not_started
from .schemas import (
    AuctionRequest,
    CreateGameRequest,
    DeclareContractRequest,
    DeviceResponse,
    GameListResponse,
    GameResponse,
    GameSummaryResponse,
    JoinGameRequest,
    PlayDominoRequest,
    PlayerResponse,
    RegisterRequest,
    SignInRequest,
    TokenResponse,
)

app = FastAPI(
    title="Texas 42",
    summary="Server-authoritative asynchronous Texas 42 (DESIGN.md §6)",
    version="0.1.0",
)
install_error_handlers(app)


#: How many times to retry a game-code collision before giving up. Collisions are ~1 in 730
#: million, so any number above one is really guarding against a pathological RNG rather than
#: expected contention.
_CODE_ATTEMPTS = 5


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --------------------------------------------------------------------------- players & sessions


@app.post("/players", status_code=status.HTTP_201_CREATED)
def register(table: TableDep, body: RegisterRequest) -> TokenResponse:
    """Creates an account and signs in the device that created it, so registering takes one
    round trip rather than two."""
    player = create_player(
        table,
        body.username,
        body.password,
        [contact.to_domain() for contact in body.contacts],
    )
    token = issue_token(table, player.player_id, body.device_label)
    return TokenResponse(player_id=player.player_id, username=player.username, token=token)


@app.post("/sessions", status_code=status.HTTP_201_CREATED)
def sign_in(table: TableDep, body: SignInRequest) -> TokenResponse:
    """Signs in one device. Each call mints a new token, so signing in on a phone leaves any
    other device signed in (DESIGN.md §6.1)."""
    player_id = authenticate(table, body.username, body.password)
    token = issue_token(table, player_id, body.device_label)
    player = get_player(table, player_id)
    return TokenResponse(player_id=player_id, username=player.username, token=token)


@app.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(table: TableDep, player_id: CurrentPlayer, token: BearerToken) -> None:
    """Revokes the token this request arrived with, and only that one, so signing out on one
    device leaves the others alone."""
    revoke_token(table, player_id, hash_token(token))


@app.get("/players/me")
def me(table: TableDep, player_id: CurrentPlayer) -> PlayerResponse:
    player = get_player(table, player_id)
    devices = [
        DeviceResponse(
            token_hash=d.token_hash,
            label=d.label,
            created_at=d.created_at,
            last_used_at=d.last_used_at,
        )
        for d in list_tokens(table, player_id)
    ]
    return PlayerResponse.of(player, devices)


@app.get("/players/me/games")
def my_games(table: TableDep, player_id: CurrentPlayer) -> GameListResponse:
    return GameListResponse(
        games=[GameSummaryResponse.of(s) for s in list_games_for_player(table, player_id)]
    )


# ------------------------------------------------------------------------------ game lifecycle


@app.post("/games", status_code=status.HTTP_201_CREATED)
def create_game(table: TableDep, player_id: CurrentPlayer, body: CreateGameRequest) -> GameResponse:
    """Opens a lobby with the caller seated. The returned ``game_id`` is the join code others
    need (DESIGN.md §4.1)."""
    config = body.house_rules.to_domain()
    username = get_player(table, player_id).username

    for _ in range(_CODE_ATTEMPTS):
        try:
            lobby = create_pending_game(
                table, new_game_code(), player_id, username, body.seat, config
            )
        except GameAlreadyExists:
            continue
        return _game_response(table, lobby, player_id)
    raise RuntimeError("could not allocate an unused game code")


@app.post("/games/{game_id}/join")
def join_game(
    table: TableDep, player_id: CurrentPlayer, game_id: GameId, body: JoinGameRequest
) -> GameResponse:
    """Takes a seat. The join that fills the fourth seat deals the first hand, so this is where
    a game usually becomes playable."""
    username = get_player(table, player_id).username
    lobby = join_seat(table, game_id, player_id, username, body.seat, rng=Random())
    return _game_response(table, lobby, player_id)


@app.get("/games/{game_id}")
def read_game(table: TableDep, player_id: CurrentPlayer, game_id: GameId) -> GameResponse:
    lobby = get_lobby(table, game_id)
    _require_seat(lobby, player_id)
    return _game_response(table, lobby, player_id)


# ---------------------------------------------------------------------------------------- moves


@app.post("/games/{game_id}/bid")
def place_bid(
    table: TableDep,
    player_id: CurrentPlayer,
    game_id: GameId,
    body: AuctionRequest,
    request_id: IdempotencyKey,
) -> GameResponse:
    """A bid, a pass, or the partner's answer to a pending plunge - discriminated on ``kind``."""
    return _submit(table, game_id, player_id, body.to_move(player_id), request_id)


@app.post("/games/{game_id}/contract")
def declare_contract(
    table: TableDep,
    player_id: CurrentPlayer,
    game_id: GameId,
    body: DeclareContractRequest,
    request_id: IdempotencyKey,
) -> GameResponse:
    return _submit(table, game_id, player_id, body.to_move(player_id), request_id)


@app.post("/games/{game_id}/play")
def play_domino(
    table: TableDep,
    player_id: CurrentPlayer,
    game_id: GameId,
    body: PlayDominoRequest,
    request_id: IdempotencyKey,
) -> GameResponse:
    return _submit(table, game_id, player_id, body.to_move(player_id), request_id)


# --------------------------------------------------------------------------------------- shared


def _submit(
    table: Table,
    game_id: GameId,
    player_id: PlayerId,
    move: Move,
    request_id: str | None,
) -> GameResponse:
    """Apply one move and persist it. The single write path behind all three move endpoints.

    Read the current state, let the engine accept or reject the move, turn the accepted move into
    events, and write them conditioned on the version we read. If somebody else wrote in between,
    ``append`` raises ``VersionConflict`` and the client gets a 409 - deliberately with no retry
    here. Contention is not a real scenario in a turn-based game: another player moving first
    means this move is out of turn anyway, and this player submitting twice is what ``request_id``
    absorbs. A retry loop would re-apply a move against a state the client never saw.

    **An idempotency key is checked twice: before, and again on failure.** ``append`` also
    recognises a duplicate ``request_id``, but on its own that is too late to help a real retry -
    by the time a client resends a move whose response it never got, the turn has usually moved
    on, and the engine rejects the move as out-of-turn long before ``append`` sees the marker. So
    the marker is read up front. That check races too, though: two retries in flight at once can
    both miss it, and the loser then fails in the engine. Hence the second look, after a
    rejection. Under an idempotency key a failure only counts if the marker *still* does not
    exist; if it appeared meanwhile, a sibling request applied this exact move and the honest
    answer is the state it produced, not an error.

    Two requests that are genuinely simultaneous can still both find nothing and one can still
    lose - the marker is written by the transaction it is racing. That is as far as this goes
    without a lock, and a client that retries once more will find the marker settled.
    """
    lobby = get_lobby(table, game_id)
    _require_seat(lobby, player_id)
    if lobby.status is GameStatus.WAITING:
        raise not_started(game_id)

    if request_id is not None and find_request(table, game_id, request_id) is not None:
        return _game_response(table, lobby, player_id)

    try:
        stored = get_state(table, game_id)
        new_state = apply_move(stored.state, move, rng=Random())
        events = events_for_move(stored.state, move, new_state)
        append(
            table,
            game_id,
            events,
            new_state,
            expected_version=stored.version,
            request_id=request_id,
        )
    except (RulesError, VersionConflict):
        if request_id is None or find_request(table, game_id, request_id) is None:
            raise
    return _game_response(table, get_lobby(table, game_id), player_id)


def _require_seat(lobby: Lobby, player_id: PlayerId) -> None:
    """Nobody sees a game they are not playing in. Spectators are out of scope for the MVP
    (DESIGN.md §2), so seating is the whole of the authorization model."""
    if lobby.seat_of(player_id) is None:
        raise not_a_player(lobby.game_id)


def _game_response(table: Table, lobby: Lobby, player_id: PlayerId) -> GameResponse:
    """A game as ``player_id`` may see it.

    The projected view is present only once the game has been dealt. ``project`` is called
    unconditionally on whatever state exists, never bypassed or partially reimplemented - it is
    the one gate hidden information passes through (invariant 5).
    """
    view: dict[str, Any] | None = None
    if lobby.status is not GameStatus.WAITING:
        try:
            view = project(get_state(table, lobby.game_id).state, player_id)
        except GameNotFound:  # pragma: no cover - only if META and STATE disagree
            view = None
    return GameResponse.of(lobby, view)
