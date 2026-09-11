"""Homework 2, Part D: authentication tests for the session endpoints.

These cover the two properties the rest of the system rests on:

  1. You cannot *claim* a role. create_session checks the request against the
     users table and refuses a mismatch, so the AuthContext the tools receive
     always describes the database's view of the caller.
  2. You cannot *reuse* someone else's proof. A token is bound to one session,
     and _authorize refuses it anywhere else.

Nothing here needs Langfuse, Docker, or a model provider key. The tests call
create_session and _authorize directly rather than starting a server, so no
model is ever invoked. Tracing is checked through recorded spans in Part E.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from server import app as server_app

# The seeded world: user 1 is a shopper, user 9002 a merchant in store 2.
SHOPPER_ID = 1
MERCHANT_ID = 9002
MERCHANT_STORE = 2


@pytest.fixture
def server(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """The app module with an empty session store, writing SQLite to tmp_path.

    _SESSIONS is module-level state, so each test starts and finishes with it
    empty. SESSIONS_DB is redirected so a test run leaves no file in the repo.
    """
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")
    server_app._SESSIONS.clear()
    yield server_app
    server_app._SESSIONS.clear()


def open_session(server: Any, user_id: int, role: str) -> dict[str, Any]:
    return server.create_session(server.SessionCreate(user_id=user_id, role=role))


# ---------------------------------------------------------------------------
# 1. A claimed role must match the database.
# ---------------------------------------------------------------------------


def test_create_session_rejects_a_role_the_database_does_not_confirm(server: Any) -> None:
    """User 9002 is a merchant, so a shopper claim is refused with 403."""
    with pytest.raises(HTTPException) as exc:
        open_session(server, MERCHANT_ID, "shopper")
    assert exc.value.status_code == 403
    # Nothing was stored: a refused claim leaves no session behind.
    assert server._SESSIONS == {}


def test_create_session_binds_the_identity_the_database_holds(server: Any) -> None:
    """The verified path: every field comes from the users table."""
    created = open_session(server, MERCHANT_ID, "merchant")
    ctx, _session = server._SESSIONS[created["session_id"]]
    assert (ctx.user_id, ctx.role, ctx.store_id) == (
        MERCHANT_ID,
        "merchant",
        MERCHANT_STORE,
    )
    # store_id reached the token without the request ever naming a store:
    # SessionCreate has no such field.
    assert server.verify_token(created["token"])["store_id"] == MERCHANT_STORE


@pytest.mark.parametrize(
    "user_id,role,expected",
    [
        (SHOPPER_ID, "wizard", 400),  # not a role at all
        (999_999, "shopper", 404),  # no such user
        (SHOPPER_ID, "support", 403),  # real role, not this user's
    ],
)
def test_create_session_rejects_bad_requests(
    server: Any, user_id: int, role: str, expected: int
) -> None:
    with pytest.raises(HTTPException) as exc:
        open_session(server, user_id, role)
    assert exc.value.status_code == expected


# ---------------------------------------------------------------------------
# 2. A token authorizes one session and no other.
# ---------------------------------------------------------------------------


def test_a_token_cannot_authorize_a_different_session(server: Any) -> None:
    """Both sessions are legitimate and both tokens are validly signed.

    What is refused is using one real token against the other's session, which
    is the payload["session_id"] != session_id check in _authorize.
    """
    shopper = open_session(server, SHOPPER_ID, "shopper")
    merchant = open_session(server, MERCHANT_ID, "merchant")

    with pytest.raises(HTTPException) as exc:
        server._authorize(merchant["session_id"], f"Bearer {shopper['token']}")
    assert exc.value.status_code == 403


def test_a_token_authorizes_its_own_session(server: Any) -> None:
    """The positive control, so the test above is not passing by accident."""
    shopper = open_session(server, SHOPPER_ID, "shopper")
    ctx = server._authorize(shopper["session_id"], f"Bearer {shopper['token']}")
    assert (ctx.user_id, ctx.role) == (SHOPPER_ID, "shopper")
    # The context came from _SESSIONS, not from the token payload.
    assert ctx is server._SESSIONS[shopper["session_id"]][0]


def test_a_rewritten_payload_does_not_survive_the_signature(server: Any) -> None:
    """Escalating the role inside the token invalidates its signature."""
    shopper = open_session(server, SHOPPER_ID, "shopper")
    body, signature = shopper["token"].rsplit(".", 1)

    payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    assert payload["role"] == "shopper"  # readable: the token is not encrypted
    payload["role"] = "support"
    forged = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode()
    ).decode()

    with pytest.raises(HTTPException) as exc:
        server._authorize(shopper["session_id"], f"Bearer {forged}.{signature}")
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "header", [None, "", "some-token", "Basic abc123", "Bearer not-a-token"]
)
def test_a_missing_or_malformed_header_is_rejected(server: Any, header: str | None) -> None:
    shopper = open_session(server, SHOPPER_ID, "shopper")
    with pytest.raises(HTTPException) as exc:
        server._authorize(shopper["session_id"], header)
    assert exc.value.status_code == 401


def test_an_unknown_session_is_rejected(server: Any) -> None:
    """_SESSIONS is in memory, so a restart invalidates a valid token."""
    shopper = open_session(server, SHOPPER_ID, "shopper")
    server._SESSIONS.clear()  # as if the server had restarted

    with pytest.raises(HTTPException) as exc:
        server._authorize(shopper["session_id"], f"Bearer {shopper['token']}")
    assert exc.value.status_code == 404
