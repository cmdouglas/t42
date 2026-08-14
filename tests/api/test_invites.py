"""Table visibility and invites over HTTP (ROADMAP.md 2.7.2, 2.7.4, DESIGN.md §6.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ._helpers import Client, seated_game


def test_visibility_round_trips_and_defaults_to_public(alice: Client) -> None:
    default_game = alice.create_game(seat=0)
    assert alice.view(default_game)["visibility"] == "public"

    private_game = alice.create_game(seat=0, visibility="invite_only")
    assert alice.view(private_game)["visibility"] == "invite_only"


def test_a_stranger_can_read_a_public_waiting_table(alice: Client, bob: Client) -> None:
    """DESIGN.md §6.2: a public table still filling up needs no invite to look at."""
    game_id = alice.create_game(seat=0)

    response = bob.get(f"/games/{game_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "WAITING"
    assert body["view"] is None


def test_a_stranger_cannot_read_an_invite_only_waiting_table(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = bob.get(f"/games/{game_id}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_PLAYER"


def test_an_invitee_can_read_an_invite_only_table_with_no_view(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    response = bob.get(f"/games/{game_id}")

    assert response.status_code == 200
    assert response.json()["view"] is None


def test_a_non_player_still_cannot_read_a_dealt_game(
    alice: Client, bob: Client, carol: Client, dave: Client, client: TestClient
) -> None:
    """A public table stops being publicly readable once it's dealt (DESIGN.md §6.2's third row) -
    the pre-2.7.2 behaviour this locks in."""
    game_id = seated_game([alice, bob, carol, dave])
    eve = Client.register(client, "eve")

    response = eve.get(f"/games/{game_id}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_PLAYER"


def test_joining_an_invite_only_table_without_an_invite_is_403(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = bob.join(game_id, 1)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_INVITED"


def test_joining_a_public_table_still_needs_no_invite(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0)

    assert bob.join(game_id, 1).status_code == 200


def test_an_invite_appears_then_disappears_once_joined(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    invite_response = alice.invite(game_id, bob.username)
    assert invite_response.status_code == 201
    assert [g["game_id"] for g in bob.my_invites()["games"]] == [game_id]

    assert bob.join(game_id, 1).status_code == 200

    assert bob.my_invites()["games"] == []


def test_an_invite_that_goes_unused_drops_off_once_the_table_fills(
    alice: Client, bob: Client, carol: Client, dave: Client, client: TestClient
) -> None:
    """ROADMAP.md 2.7.2: the enrichment drops any game no longer ``WAITING``, so a pending invite
    to a table that filled up without the invitee simply vanishes rather than dangling."""
    eve = Client.register(client, "eve")
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)
    for username in (carol.username, dave.username, eve.username):
        alice.invite(game_id, username)
    carol.join(game_id, 1)
    dave.join(game_id, 2)
    eve.join(game_id, 3)

    assert bob.my_invites()["games"] == []


def test_a_seated_player_can_list_who_is_invited(alice: Client, bob: Client, carol: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    response = alice.list_invites(game_id)

    assert response.status_code == 200
    invites = response.json()["invites"]
    assert [i["username"] for i in invites] == [bob.username]
    assert invites[0]["player_id"] == bob.player_id


def test_a_fresh_table_has_no_invites(alice: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = alice.list_invites(game_id)

    assert response.status_code == 200
    assert response.json()["invites"] == []


def test_an_invite_drops_off_the_game_list_once_joined(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    bob.join(game_id, 1)

    assert alice.list_invites(game_id).json()["invites"] == []


def test_a_non_seated_caller_cannot_list_invites(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = bob.list_invites(game_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_PLAYER"


def test_listing_invites_for_an_unknown_game_is_404(alice: Client) -> None:
    response = alice.list_invites("NOPE12")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GAME_NOT_FOUND"


def test_inviting_an_unknown_username_is_404(alice: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = alice.invite(game_id, "nobody-here")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAYER_NOT_FOUND"


def test_inviting_an_already_seated_player_is_409(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)
    bob.join(game_id, 1)

    response = alice.invite(game_id, bob.username)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_SEATED"


def test_inviting_into_a_dealt_game_is_409(
    alice: Client, bob: Client, carol: Client, dave: Client, client: TestClient
) -> None:
    game_id = seated_game([alice, bob, carol, dave])
    eve = Client.register(client, "eve")

    response = alice.invite(game_id, eve.username)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GAME_NOT_JOINABLE"


def test_a_non_seated_caller_cannot_invite(alice: Client, bob: Client, carol: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")

    response = bob.invite(game_id, carol.username)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_PLAYER"


def test_the_invitee_can_decline_their_own_invite(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    response = bob.decline_or_revoke_invite(game_id, bob.player_id)

    assert response.status_code == 204
    assert bob.my_invites()["games"] == []


def test_a_seated_player_can_revoke_someone_elses_invite(alice: Client, bob: Client) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    response = alice.decline_or_revoke_invite(game_id, bob.player_id)

    assert response.status_code == 204
    assert bob.my_invites()["games"] == []


def test_a_stranger_cannot_revoke_someone_elses_invite(
    alice: Client, bob: Client, carol: Client
) -> None:
    game_id = alice.create_game(seat=0, visibility="invite_only")
    alice.invite(game_id, bob.username)

    response = carol.decline_or_revoke_invite(game_id, bob.player_id)

    assert response.status_code == 403
    assert [g["game_id"] for g in bob.my_invites()["games"]] == [game_id]
