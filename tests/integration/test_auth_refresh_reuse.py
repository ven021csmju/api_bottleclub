"""A refresh token used again after its rotation (Phase 45, item 2).

The old token is 401 REFRESH_TOKEN_REUSED and its family is revoked: the
login it came from and every token its refreshes rotated it into, so whoever
holds the newer one (the owner or a thief) logs in again. The user's other
logins stay. Body or cookie alike. A token stored before migration 021 (no
family) is linked to its successor at its first refresh. Up to v0.1.19 the
old token was 401 and the newer one went on working.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.integration.cookie_fixtures import (  # noqa: F401  (fixtures)
    API, BROWSER, COOKIE, REFRESH_COOKIE, cookie_origin, https, is_live, login, refresh_cookie,
)

pytestmark = pytest.mark.integration


def _refresh(client: TestClient, token: str):
    return client.post(f"{API}/auth/refresh", json={"refresh_token": token})


def _reused(resp) -> None:
    assert (resp.status_code, resp.json()["code"]) == (401, "REFRESH_TOKEN_REUSED"), resp.text


def test_a_reused_body_token_revokes_its_family_only(client: TestClient, session, seed_user):
    first = login(client, seed_user).json()["data"]["refresh_token"]
    other_login = login(client, seed_user).json()["data"]["refresh_token"]
    second = _refresh(client, first).json()["data"]["refresh_token"]
    third = _refresh(client, second).json()["data"]["refresh_token"]

    _reused(_refresh(client, first))
    assert (is_live(session, third), is_live(session, other_login)) == (False, True)
    assert _refresh(client, third).status_code == 401
    assert _refresh(client, other_login).status_code == 200


def test_a_reused_cookie_does_the_same(https: TestClient, session, seed_user):
    old = refresh_cookie(login(https, seed_user, COOKIE))["value"]
    resp = https.post(f"{API}/auth/refresh", headers=BROWSER)
    assert resp.status_code == 200, resp.text
    new = refresh_cookie(resp)["value"]

    _reused(https.post(f"{API}/auth/refresh", headers={**BROWSER, "Cookie": f"{REFRESH_COOKIE}={old}"}))
    assert is_live(session, new) is False
    assert https.post(f"{API}/auth/refresh", headers=BROWSER).status_code == 401  # the jar's newer one


def test_the_session_of_a_password_change_stays(client: TestClient, session, seed_user):
    """The change revokes every older token and starts a family of its own."""
    before = login(client, seed_user).json()["data"]
    resp = client.post(f"{API}/auth/change-password", headers={"Authorization": f"Bearer {before['access_token']}"},
                       json={"current_password": seed_user["password"], "new_password": "A-New-Pass-4567"})
    assert resp.status_code == 200, resp.text
    after = resp.json()["data"]["refresh_token"]

    assert _refresh(client, before["refresh_token"]).status_code == 401
    assert is_live(session, after) is True
    assert _refresh(client, after).status_code == 200


def test_a_token_of_before_021_gets_a_family_at_its_refresh(client: TestClient, session, seed_user):
    from app.db.models import RefreshToken
    from app.shared.security import create_refresh_token, hash_token

    old = create_refresh_token(user_id=seed_user["user_id"])
    session.add(RefreshToken(user_id=seed_user["user_id"], token_hash=hash_token(old), is_revoked=False,
                             expires_at=_in_a_week()))
    session.commit()
    new = _refresh(client, old).json()["data"]["refresh_token"]
    session.expire_all()
    families = session.scalars(select(RefreshToken.family_id)
                               .where(RefreshToken.token_hash.in_([hash_token(old), hash_token(new)]))).all()
    assert len(families) == 2 and families[0] is not None and len(set(families)) == 1

    _reused(_refresh(client, old))
    assert is_live(session, new) is False


def test_an_unknown_token_revokes_nothing(client: TestClient, session, seed_user):
    from app.shared.security import create_refresh_token

    live = login(client, seed_user).json()["data"]["refresh_token"]
    resp = _refresh(client, create_refresh_token(user_id=seed_user["user_id"]))
    assert (resp.status_code, resp.json()["code"]) == (401, "UNAUTHORIZED"), resp.text
    assert is_live(session, live) is True


def _in_a_week():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(days=7)
