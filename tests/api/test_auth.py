"""Registration, sign-in and bearer tokens over HTTP (ROADMAP.md 2.5, DESIGN.md §6.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ._helpers import PASSWORD, Client


def test_registering_returns_a_usable_token(client: TestClient) -> None:
    response = client.post("/players", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"

    me = client.get("/players/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["player_id"] == body["player_id"]


def test_a_duplicate_username_is_a_conflict(client: TestClient, alice: Client) -> None:
    response = client.post("/players", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        pytest.param({"username": "", "password": PASSWORD}, "blank", id="blank username"),
        pytest.param({"username": "a b", "password": PASSWORD}, "space", id="username with space"),
        pytest.param({"username": "alice", "password": "short"}, "short", id="short password"),
        pytest.param({"username": "alice"}, "missing", id="missing password"),
    ],
)
def test_malformed_registration_is_a_422(
    client: TestClient, payload: dict[str, str], reason: str
) -> None:
    """FastAPI's own validation owns 422, which is why rules rejections use 400 instead."""
    assert client.post("/players", json=payload).status_code == 422


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    """A misspelled field must not be silently ignored, the same way an unrecognised house-rule
    option key is an error rather than a no-op (DESIGN.md §5.1)."""
    response = client.post(
        "/players", json={"username": "alice", "password": PASSWORD, "psasword": "typo"}
    )

    assert response.status_code == 422


def test_sign_in_issues_a_second_independent_token(client: TestClient, alice: Client) -> None:
    """The cross-device requirement: signing in on a phone must not disturb the desktop."""
    response = client.post(
        "/sessions",
        json={"username": "alice", "password": PASSWORD, "device_label": "phone"},
    )

    assert response.status_code == 201
    phone_token = response.json()["token"]
    assert phone_token != alice.token

    for token in (alice.token, phone_token):
        assert (
            client.get("/players/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"username": "alice", "password": "wrong-password"}, id="wrong password"),
        pytest.param({"username": "nobody", "password": PASSWORD}, id="unknown username"),
    ],
)
def test_bad_credentials_are_401_and_indistinguishable(
    client: TestClient, alice: Client, payload: dict[str, str]
) -> None:
    """The two failures must look identical, or the endpoint tells an attacker which usernames
    exist (DESIGN.md §6.1)."""
    response = client.post("/sessions", json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "invalid username or password"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no header"),
        pytest.param({"Authorization": "opaque-token"}, id="no scheme"),
        pytest.param({"Authorization": "Basic abc"}, id="wrong scheme"),
        pytest.param({"Authorization": "Bearer "}, id="empty token"),
    ],
)
def test_a_missing_or_malformed_header_is_401(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/players/me", headers=headers).status_code == 401


def test_an_unissued_token_is_401(client: TestClient) -> None:
    response = client.get("/players/me", headers={"Authorization": "Bearer made-up"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_signing_out_revokes_only_this_device(client: TestClient, alice: Client) -> None:
    phone = client.post(
        "/sessions", json={"username": "alice", "password": PASSWORD, "device_label": "phone"}
    ).json()["token"]

    assert alice.delete("/sessions/current").status_code == 204

    assert alice.get("/players/me").status_code == 401
    assert (
        client.get("/players/me", headers={"Authorization": f"Bearer {phone}"}).status_code == 200
    )


def test_me_lists_devices_without_exposing_any_token(client: TestClient, alice: Client) -> None:
    client.post(
        "/sessions", json={"username": "alice", "password": PASSWORD, "device_label": "phone"}
    )

    body = alice.get("/players/me").json()

    assert {device["label"] for device in body["devices"]} == {"", "phone"}
    assert alice.token not in str(body)


def test_contacts_are_channels_and_are_optional(client: TestClient) -> None:
    """Nothing requires an email, and the shape is a list of channels so Phase 4 can add a kind
    without a migration (DESIGN.md §12)."""
    with_email = Client.register(
        client, "alice", contacts=[{"kind": "email", "address": "a@example.com"}]
    )
    without = Client.register(client, "bob")

    assert with_email.http.get("/players/me", headers=with_email.auth).json()["contacts"] == [
        {"kind": "email", "address": "a@example.com", "verified": False, "notify": True}
    ]
    assert without.http.get("/players/me", headers=without.auth).json()["contacts"] == []


def test_the_password_never_appears_in_any_response(client: TestClient, alice: Client) -> None:
    assert PASSWORD not in alice.get("/players/me").text
