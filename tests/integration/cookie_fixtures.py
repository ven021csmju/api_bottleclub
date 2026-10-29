"""The refresh-token cookie in tests (Phase 45).

``https``: the app over https://testserver, so the client's cookie jar sends
the Secure cookie back as a browser would. ``cookie_origin``: the origin
AUTH_COOKIE_ORIGINS (and CORS_ORIGINS) allows in these tests.
"""
from __future__ import annotations

import hashlib
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.security import hash_token

API = "/api/v1"
ORIGIN = "https://pos.wayneven.uk"
#: A second web that may use the cookie, and one that is in CORS_ORIGINS only.
ADMIN = "https://admin.wayneven.uk"
CORS_ONLY = "https://shop.wayneven.uk"
COOKIE = {"X-Auth-Mode": "cookie"}
#: What the web sends in cookie mode.
BROWSER = {**COOKIE, "Origin": ORIGIN}


def cookie_of(origin: str, prefix: str = "__Host-bc_refresh") -> str:
    """The cookie of a web, written out (not imported: the name is the contract):
    prefix + "_" + the first 8 hex of sha256(origin)."""
    return f"{prefix}_{hashlib.sha256(origin.encode()).hexdigest()[:8]}"


REFRESH_COOKIE = cookie_of(ORIGIN)


@pytest.fixture()
def cookie_origin(monkeypatch) -> str:
    from app.config.settings import settings

    monkeypatch.setattr(settings, "CORS_ORIGINS", f"{ORIGIN},{ADMIN},{CORS_ONLY}")
    monkeypatch.setattr(settings, "AUTH_COOKIE_ORIGINS", f"{ORIGIN},{ADMIN}")
    return ORIGIN


@pytest.fixture()
def https(client: TestClient, cookie_origin: str) -> Generator[TestClient, None, None]:
    yield TestClient(client.app, base_url="https://testserver", raise_server_exceptions=False)


def set_cookies(resp) -> list[str]:
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def refresh_cookie(resp, origin: str = ORIGIN) -> dict[str, str] | None:
    """The refresh cookie of ``origin`` the answer sets: its value and attributes (lower-case names)."""
    for header in set_cookies(resp):
        name, _, rest = header.partition("=")
        if name == cookie_of(origin):
            value, *attrs = [part.strip() for part in rest.split(";")]
            parsed = {"value": value.strip('"')}
            for attr in attrs:
                key, _, val = attr.partition("=")
                parsed[key.lower()] = val
            return parsed
    return None


def is_live(session: Session, raw: str) -> bool | None:
    """True: stored and not revoked; False: revoked; None: not stored."""
    from app.db.models import RefreshToken

    session.expire_all()
    record = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    return None if record is None else not record.is_revoked


def login(client: TestClient, user: dict, headers: dict | None = None):
    return client.post(f"{API}/auth/login", headers=headers or {},
                       json={"username": user["username"], "password": user["password"]})
