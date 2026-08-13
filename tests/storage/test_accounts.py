"""Accounts and auth tokens (ROADMAP.md 2.1)."""

from __future__ import annotations

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from t42.storage.accounts import (
    ContactChannel,
    authenticate,
    create_player,
    get_player,
    hash_token,
    issue_token,
    list_tokens,
    player_for_token,
    revoke_token,
)
from t42.storage.errors import InvalidCredentials, InvalidToken, UsernameTaken


def test_create_player_round_trips_through_get_player(table: Table) -> None:
    player = create_player(
        table,
        "Charlie",
        "correct horse battery staple",
        [ContactChannel(kind="email", address="c@example.com")],
    )

    assert get_player(table, player.player_id) == player
    assert player.username == "Charlie"
    assert player.contacts == (ContactChannel("email", "c@example.com", verified=False),)


def test_a_player_needs_no_contact_channels(table: Table) -> None:
    """Nothing requires an email address (DESIGN.md §12): notifications are a later, optional
    thing rather than a condition of having an account."""
    player = create_player(table, "hermit", "pw")

    assert get_player(table, player.player_id).contacts == ()


def test_usernames_are_unique_case_insensitively(table: Table) -> None:
    create_player(table, "Charlie", "pw")

    with pytest.raises(UsernameTaken):
        create_player(table, "charlie", "different-password")


def test_player_ids_are_opaque_not_usernames(table: Table) -> None:
    """Invariant 6 makes the event log immutable, so a renameable username must never be what
    identifies a player in it."""
    player = create_player(table, "charlie", "pw")

    assert player.player_id != "charlie"
    assert "charlie" not in player.player_id.lower()


def test_the_password_hash_never_leaves_the_module(table: Table) -> None:
    player = create_player(table, "charlie", "hunter2")

    assert "hunter2" not in repr(get_player(table, player.player_id))

    stored = table.get_item(Key={"PK": f"PLAYER#{player.player_id}", "SK": "PROFILE"})["Item"]
    assert "hunter2" not in str(stored["password_hash"])
    assert str(stored["password_hash"]).startswith("scrypt$")


def test_authenticate_accepts_the_right_password(table: Table) -> None:
    player = create_player(table, "charlie", "hunter2")

    assert authenticate(table, "charlie", "hunter2") == player.player_id
    assert authenticate(table, "CHARLIE", "hunter2") == player.player_id


@pytest.mark.parametrize(
    ("username", "password"),
    [
        pytest.param("charlie", "wrong", id="wrong password"),
        pytest.param("nobody", "hunter2", id="unknown username"),
    ],
)
def test_authenticate_rejects_bad_credentials(table: Table, username: str, password: str) -> None:
    create_player(table, "charlie", "hunter2")

    with pytest.raises(InvalidCredentials) as excinfo:
        authenticate(table, username, password)

    # The message must not say which half was wrong, or the endpoint becomes a username oracle.
    assert "username" not in str(excinfo.value).replace("invalid username or password", "")


def test_issue_token_resolves_back_to_its_player(table: Table) -> None:
    player = create_player(table, "charlie", "pw")
    token = issue_token(table, player.player_id, "laptop")

    assert player_for_token(table, token) == player.player_id


def test_an_unissued_token_is_rejected(table: Table) -> None:
    with pytest.raises(InvalidToken):
        player_for_token(table, "not-a-real-token")


def test_only_the_token_hash_is_stored(table: Table) -> None:
    player = create_player(table, "charlie", "pw")
    token = issue_token(table, player.player_id)

    assert table.get_item(Key={"PK": f"TOKEN#{token}", "SK": "TOKEN"}).get("Item") is None
    stored = table.get_item(Key={"PK": f"TOKEN#{hash_token(token)}", "SK": "TOKEN"})["Item"]
    assert stored["player_id"] == player.player_id
    assert token not in str(stored)


def test_each_device_gets_its_own_token(table: Table) -> None:
    """The requirement that motivates per-device tokens: signing in on a phone must not disturb
    a session already running on a desktop (DESIGN.md §6.1)."""
    player = create_player(table, "charlie", "pw")
    desktop = issue_token(table, player.player_id, "desktop")
    phone = issue_token(table, player.player_id, "phone")

    assert desktop != phone
    assert player_for_token(table, desktop) == player.player_id
    assert player_for_token(table, phone) == player.player_id
    assert {d.label for d in list_tokens(table, player.player_id)} == {"desktop", "phone"}


def test_revoking_one_device_leaves_the_others_signed_in(table: Table) -> None:
    player = create_player(table, "charlie", "pw")
    desktop = issue_token(table, player.player_id, "desktop")
    phone = issue_token(table, player.player_id, "phone")

    revoke_token(table, player.player_id, hash_token(phone))

    assert player_for_token(table, desktop) == player.player_id
    with pytest.raises(InvalidToken):
        player_for_token(table, phone)
    assert [d.label for d in list_tokens(table, player.player_id)] == ["desktop"]


def test_a_player_cannot_revoke_another_players_token(table: Table) -> None:
    victim = create_player(table, "victim", "pw")
    attacker = create_player(table, "attacker", "pw")
    victim_token = issue_token(table, victim.player_id, "laptop")

    revoke_token(table, attacker.player_id, hash_token(victim_token))

    assert player_for_token(table, victim_token) == victim.player_id


def test_revoking_twice_is_a_no_op(table: Table) -> None:
    player = create_player(table, "charlie", "pw")
    token = issue_token(table, player.player_id)
    digest = hash_token(token)

    revoke_token(table, player.player_id, digest)
    revoke_token(table, player.player_id, digest)

    assert list_tokens(table, player.player_id) == ()
