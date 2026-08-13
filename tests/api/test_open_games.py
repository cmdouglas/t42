"""The public-tables browse over HTTP (ROADMAP.md 2.7.3, 2.7.4, DESIGN.md §4.1, §6.2)."""

from __future__ import annotations

from ._helpers import Client


def _open_game_ids(player: Client) -> list[str]:
    response = player.get("/games/open")
    assert response.status_code == 200, response.text
    return [g["game_id"] for g in response.json()["games"]]


def test_a_public_waiting_table_appears(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0)

    assert game_id in _open_game_ids(bob)


def test_an_invite_only_table_never_appears(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    assert game_id not in _open_game_ids(bob)


def test_a_dealt_table_drops_off(alice: Client, bob: Client, carol: Client, dave: Client) -> None:
    game_id = alice.create_game(seat=0)
    bob.join(game_id, 1)
    carol.join(game_id, 2)
    assert game_id in _open_game_ids(dave)

    dave.join(game_id, 3)  # the fourth join deals it

    assert game_id not in _open_game_ids(alice)


def test_the_callers_own_table_is_filtered_out(alice: Client) -> None:
    """Free, per ROADMAP.md 2.7.3: the index already carries the seats map."""
    game_id = alice.create_game(seat=0)

    assert game_id not in _open_game_ids(alice)


def test_open_games_response_has_no_view(alice: Client, bob: Client) -> None:
    alice.create_game(seat=0)

    games = bob.get("/games/open").json()["games"]

    assert games and all(g["view"] is None for g in games)
