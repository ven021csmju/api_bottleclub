"""Cookie mode at login, refresh and change-password (Phase 45, item 1).

``X-Auth-Mode: cookie`` sets ``__Host-bc_refresh`` (HttpOnly; Secure;
SameSite=Strict; Path=/; no Domain) and leaves refresh_token out of the body;
without the header the body carries it as before (vercel.app, tests,
scripts). v0.1.19 had only the body.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from tests.integration.cookie_fixtures import (  # noqa: F401  (fixtures)
    API, COOKIE, cookie_origin, https, is_live, login, refresh_cookie, set_cookies,
)

pytestmark = pytest.mark.integration


def _the_cookie(resp) -> str:
    cookie = refresh_cookie(resp)
    assert cookie is not None, set_cookies(resp)
    attrs = {k for k in cookie if k != "value"}
    assert attrs == {"httponly", "secure", "samesite", "path", "max-age"}, cookie
    assert (cookie["samesite"].lower(), cookie["path"]) == ("strict", "/")
    assert int(cookie["max-age"]) == settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    return cookie["value"]


@pytest.mark.parametrize("mode", ["cookie", "Cookie", " COOKIE "])
def test_login_in_cookie_mode(https: TestClient, session, seed_user, mode):
    resp = login(https, seed_user, {"X-Auth-Mode": mode})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert "refresh_token" not in body
    assert body["access_token"] and body["token_type"] == "bearer"
    assert is_live(session, _the_cookie(resp)) is True


def test_login_without_the_header_is_as_before(https: TestClient, session, seed_user):
    resp = login(https, seed_user, {"X-Auth-Mode": "body"})
    assert resp.status_code == 200, resp.text
    assert is_live(session, resp.json()["data"]["refresh_token"]) is True
    assert set_cookies(resp) == []


def test_refresh_with_the_token_in_the_body_answers_in_the_cookie(https: TestClient, session, seed_user):
    old = login(https, seed_user).json()["data"]["refresh_token"]
    resp = https.post(f"{API}/auth/refresh", headers=COOKIE, json={"refresh_token": old})
    assert resp.status_code == 200, resp.text
    assert "refresh_token" not in resp.json()["data"]
    new = _the_cookie(resp)
    assert (is_live(session, old), is_live(session, new)) == (False, True)


def test_change_password_in_cookie_mode(https: TestClient, session, seed_user):
    access = login(https, seed_user).json()["data"]["access_token"]
    resp = https.post(f"{API}/auth/change-password", headers={**COOKIE, "Authorization": f"Bearer {access}"},
                      json={"current_password": seed_user["password"], "new_password": "A-New-Pass-4567"})
    assert resp.status_code == 200, resp.text
    assert "refresh_token" not in resp.json()["data"]
    assert is_live(session, _the_cookie(resp)) is True


def test_over_plain_http_outside_production_it_is_bc_refresh(client: TestClient, session, seed_user, cookie_origin):
    """A browser refuses a __Host- cookie from http://localhost (Chromium: InvalidPrefix)
    but keeps a Secure one: a web on localhost against a staging API over http."""
    resp = login(client, seed_user, COOKIE)
    assert resp.status_code == 200, resp.text
    assert refresh_cookie(resp) is None
    (header,) = set_cookies(resp)
    name, _, rest = header.partition("=")
    assert name == "bc_refresh"
    assert {"httponly", "secure", "samesite=strict", "path=/"} <= {a.strip().lower() for a in rest.split(";")[1:]}
    old = rest.split(";")[0].strip('"')
    resp = client.post(f"{API}/auth/refresh", headers={**COOKIE, "Origin": cookie_origin, "Cookie": f"bc_refresh={old}"})
    assert resp.status_code == 200, resp.text
    assert is_live(session, old) is False


def test_production_is_always_host_prefixed(client: TestClient, seed_user, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    resp = login(client, seed_user, COOKIE)  # http as uvicorn sees it behind a proxy that does not say https
    assert resp.status_code == 200, resp.text
    assert refresh_cookie(resp) is not None
