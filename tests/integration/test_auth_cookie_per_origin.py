"""One refresh cookie per web (Phase 45b).

The cookie belongs to the API's host, so every web of one browser would send
the same one: a manager's login in the admin web became the POS tab's session
at its next refresh (v0.1.20). Its name is that of the request's Origin,
``__Host-bc_refresh_<first 8 hex of sha256(origin)>``: set, read and deleted
by that name only. A cookie-mode request from no allowed origin is 403
CSRF_REJECTED before anything is done (no login, no token stored).
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.shared.security import hash_password
from tests.integration.cookie_fixtures import (  # noqa: F401  (fixtures)
    ADMIN, API, COOKIE, CORS_ONLY, ORIGIN, cookie_of, cookie_origin, https, is_live, login, refresh_cookie,
    set_cookies,
)

pytestmark = pytest.mark.integration

POS = {**COOKIE, "Origin": ORIGIN}
ADMIN_WEB = {**COOKIE, "Origin": ADMIN}


@pytest.fixture()
def manager(session, seed_org) -> dict:
    from app.db.models import User

    user = User(organization_id=seed_org, username="branchmanager", email="manager@test.com",
                password_hash=hash_password("Manager1234!"), display_name="Manager", status="active")
    session.add(user)
    session.commit()
    return {"user_id": user.id, "username": "branchmanager", "password": "Manager1234!"}


def _me(client: TestClient, headers: dict) -> str:
    resp = client.post(f"{API}/auth/refresh", headers=headers)
    assert resp.status_code == 200, resp.text
    access = resp.json()["data"]["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    return me.json()["data"]["username"]


def test_the_name_is_of_the_origin():
    assert cookie_of(ORIGIN) == "__Host-bc_refresh_" + hashlib.sha256(ORIGIN.encode()).hexdigest()[:8]
    assert cookie_of(ORIGIN) != cookie_of(ADMIN)


def test_two_webs_two_accounts_each_keeps_its_own(https: TestClient, session, seed_user, manager):
    pos = login(https, seed_user, POS)
    admin = login(https, manager, ADMIN_WEB)  # same browser (one cookie jar), another web
    assert pos.status_code == admin.status_code == 200, admin.text
    assert refresh_cookie(pos, ORIGIN) and refresh_cookie(admin, ADMIN)
    assert refresh_cookie(admin, ORIGIN) is None  # the admin login leaves the POS cookie alone

    assert _me(https, POS) == seed_user["username"]
    assert _me(https, ADMIN_WEB) == manager["username"]
    assert _me(https, POS) == seed_user["username"]


def test_logout_of_one_web_leaves_the_other(https: TestClient, session, seed_user, manager):
    pos = login(https, seed_user, POS).json()["data"]
    login(https, manager, ADMIN_WEB)
    resp = https.post(f"{API}/auth/logout", headers={**POS, "Authorization": f"Bearer {pos['access_token']}"})
    assert resp.status_code == 204, resp.text
    assert [c.split("=")[0] for c in set_cookies(resp)] == [cookie_of(ORIGIN)]

    resp = https.post(f"{API}/auth/refresh", headers=POS)
    assert (resp.status_code, resp.json()["code"]) == (401, "REFRESH_TOKEN_MISSING"), resp.text
    assert _me(https, ADMIN_WEB) == manager["username"]


def test_a_cookie_of_another_web_is_not_read(https: TestClient, session, seed_user):
    """Only the request's origin's cookie counts, even when the browser sends others."""
    login(https, seed_user, POS)
    resp = https.post(f"{API}/auth/refresh", headers=ADMIN_WEB)
    assert (resp.status_code, resp.json()["code"]) == (401, "REFRESH_TOKEN_MISSING"), resp.text


@pytest.mark.parametrize("headers", [COOKIE, {**COOKIE, "Origin": CORS_ONLY}, {**COOKIE, "Origin": "null"}])
@pytest.mark.parametrize("route", ["login", "change-password"])
def test_cookie_mode_from_no_allowed_origin_does_nothing(https: TestClient, session, seed_user, headers, route):
    from app.db.models import RefreshToken

    session.expire_all()
    before = session.scalar(select(func.count()).select_from(RefreshToken))
    if route == "login":
        resp = login(https, seed_user, headers)
    else:
        access = login(https, seed_user).json()["data"]["access_token"]
        before += 1
        resp = https.post(f"{API}/auth/change-password", headers={**headers, "Authorization": f"Bearer {access}"},
                          json={"current_password": seed_user["password"], "new_password": "A-New-Pass-4567"})
    assert (resp.status_code, resp.json()["code"]) == (403, "CSRF_REJECTED"), resp.text
    assert set_cookies(resp) == []
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(RefreshToken)) == before
    if route == "change-password":
        assert login(https, seed_user).status_code == 200  # the password did not change


def test_a_body_token_with_cookie_mode_needs_an_allowed_origin(https: TestClient, session, seed_user):
    old = login(https, seed_user).json()["data"]["refresh_token"]
    resp = https.post(f"{API}/auth/refresh", headers=COOKIE, json={"refresh_token": old})
    assert (resp.status_code, resp.json()["code"]) == (403, "CSRF_REJECTED"), resp.text
    assert is_live(session, old) is True
