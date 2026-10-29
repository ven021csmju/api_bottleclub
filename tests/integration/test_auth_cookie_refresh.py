"""POST /auth/refresh from the cookie, and its CSRF check (Phase 45, items 2-3).

With no refresh_token in the body the token is the cookie's, rotated: a new
cookie, the old token revoked. The cookie is read only for a request with
``X-Auth-Mode: cookie`` whose Origin is in AUTH_COOKIE_ORIGINS; any other is
403 CSRF_REJECTED and the token is left as it was. A body token works as
before, header or not. Up to v0.1.19 refresh_token was required in the body
(422 without it) and the cookie was never read.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.cookie_fixtures import (  # noqa: F401  (fixtures)
    API, BROWSER, COOKIE, ORIGIN, REFRESH_COOKIE, cookie_origin, https, is_live, login, refresh_cookie,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def logged_in(https: TestClient, seed_user) -> str:
    """Logged in in cookie mode: the client's jar has the cookie; its token."""
    resp = login(https, seed_user, COOKIE)
    assert resp.status_code == 200, resp.text
    return refresh_cookie(resp)["value"]


def _refresh(client: TestClient, headers: dict, **kwargs):
    return client.post(f"{API}/auth/refresh", headers=headers, **kwargs)


@pytest.mark.parametrize("body", [{}, {"json": {}}, {"json": {"refresh_token": None}}, {"json": {"refresh_token": ""}}])
def test_the_cookie_is_rotated(https: TestClient, session, logged_in, body):
    resp = _refresh(https, BROWSER, **body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "refresh_token" not in data
    new = refresh_cookie(resp)["value"]
    assert new != logged_in
    assert (is_live(session, logged_in), is_live(session, new)) == (False, True)
    me = https.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200, me.text
    # the jar now holds the new one: it refreshes again
    assert _refresh(https, BROWSER).status_code == 200


@pytest.mark.parametrize("headers", [
    {},                                                     # a body client that forgot the token
    {"Origin": ORIGIN},                                     # no X-Auth-Mode
    {"X-Auth-Mode": "body", "Origin": ORIGIN},
    COOKIE,                                                 # no Origin
    {**COOKIE, "Origin": "https://admin.wayneven.uk"},      # in CORS_ORIGINS, not AUTH_COOKIE_ORIGINS
    {**COOKIE, "Origin": "https://evil.wayneven.uk"},       # same site, another origin
    {**COOKIE, "Origin": "https://pos.wayneven.uk.evil.com"},
    {**COOKIE, "Origin": "http://pos.wayneven.uk"},
    {**COOKIE, "Origin": "null"},
])
def test_any_other_request_is_csrf_rejected(https: TestClient, session, logged_in, headers):
    resp = _refresh(https, headers)
    assert (resp.status_code, resp.json()["code"]) == (403, "CSRF_REJECTED"), resp.text
    assert refresh_cookie(resp) is None
    assert is_live(session, logged_in) is True


def test_no_origin_may_when_none_is_set(https: TestClient, session, logged_in, monkeypatch):
    from app.config.settings import settings

    monkeypatch.setattr(settings, "AUTH_COOKIE_ORIGINS", "")
    resp = _refresh(https, BROWSER)
    assert (resp.status_code, resp.json()["code"]) == (403, "CSRF_REJECTED"), resp.text
    assert is_live(session, logged_in) is True


def test_an_allowed_request_without_the_cookie_is_401(https: TestClient):
    resp = _refresh(https, BROWSER)
    assert (resp.status_code, resp.json()["code"]) == (401, "REFRESH_TOKEN_MISSING"), resp.text


def test_a_token_in_the_body_needs_no_origin(https: TestClient, session, seed_user):
    old = login(https, seed_user).json()["data"]["refresh_token"]
    resp = _refresh(https, {}, json={"refresh_token": old})
    assert resp.status_code == 200, resp.text
    assert is_live(session, resp.json()["data"]["refresh_token"]) is True
    assert refresh_cookie(resp) is None


def test_the_body_token_wins_over_the_cookie(https: TestClient, session, seed_user, logged_in):
    other = login(https, seed_user).json()["data"]["refresh_token"]
    resp = _refresh(https, {}, json={"refresh_token": other})
    assert resp.status_code == 200, resp.text
    assert (is_live(session, other), is_live(session, logged_in)) == (False, True)


def test_a_cookie_that_is_not_a_token_is_401(https: TestClient):
    resp = _refresh(https, {**BROWSER, "Cookie": f"{REFRESH_COOKIE}=not-a-token"})
    assert resp.status_code == 401, resp.text
