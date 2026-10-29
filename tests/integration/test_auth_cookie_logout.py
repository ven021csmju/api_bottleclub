"""POST /auth/logout and the cookie (Phase 45, item 4).

In either mode the answer deletes the cookie (Max-Age=0, with the attributes
it was set with). With X-Auth-Mode: cookie and no body token it revokes the
cookie's token, behind the same CSRF check as refresh (403 CSRF_REJECTED);
the user's other logins stay. Up to v0.1.19 logout never touched the cookie.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.cookie_fixtures import (  # noqa: F401  (fixtures)
    API, BROWSER, COOKIE, cookie_origin, https, is_live, login, refresh_cookie,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def web(https: TestClient, seed_user) -> dict:
    """Logged in in cookie mode: the access token and the cookie's token."""
    resp = login(https, seed_user, COOKIE)
    assert resp.status_code == 200, resp.text
    return {"access": resp.json()["data"]["access_token"], "refresh": refresh_cookie(resp)["value"]}


def _logout(client: TestClient, access: str, headers: dict | None = None, **kwargs):
    return client.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {access}", **(headers or {})},
                       **kwargs)


def _deleted(resp) -> None:
    assert resp.status_code == 204, resp.text
    cookie = refresh_cookie(resp)
    assert cookie is not None and cookie["value"] == "" and cookie["max-age"] == "0", cookie
    assert {"httponly", "secure", "samesite", "path"} <= set(cookie) and cookie["path"] == "/"
    assert "domain" not in cookie


def test_cookie_mode_revokes_the_cookies_token_and_deletes_it(https: TestClient, session, seed_user, web):
    other_login = login(https, seed_user).json()["data"]["refresh_token"]
    resp = _logout(https, web["access"], BROWSER)
    _deleted(resp)
    assert (is_live(session, web["refresh"]), is_live(session, other_login)) == (False, True)
    # the jar dropped the cookie: nothing left to refresh with
    resp = https.post(f"{API}/auth/refresh", headers=BROWSER)
    assert (resp.status_code, resp.json()["code"]) == (401, "REFRESH_TOKEN_MISSING"), resp.text


@pytest.mark.parametrize("headers", [COOKIE, {**COOKIE, "Origin": "https://admin.wayneven.uk"}])
def test_cookie_mode_from_another_origin_is_csrf_rejected(https: TestClient, session, web, headers):
    resp = _logout(https, web["access"], headers)
    assert (resp.status_code, resp.json()["code"]) == (403, "CSRF_REJECTED"), resp.text
    assert is_live(session, web["refresh"]) is True


def test_body_mode_deletes_the_cookie_too(https: TestClient, session, seed_user, web):
    tokens = login(https, seed_user).json()["data"]
    _deleted(_logout(https, tokens["access_token"], json={"refresh_token": tokens["refresh_token"]}))
    assert (is_live(session, tokens["refresh_token"]), is_live(session, web["refresh"])) == (False, True)


def test_no_token_anywhere_revokes_every_session_as_before(https: TestClient, session, seed_user, web):
    tokens = login(https, seed_user).json()["data"]
    _deleted(_logout(https, tokens["access_token"]))
    assert (is_live(session, tokens["refresh_token"]), is_live(session, web["refresh"])) == (False, False)
