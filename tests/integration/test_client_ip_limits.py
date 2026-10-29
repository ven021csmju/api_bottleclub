"""The login rate limit and login_attempts per client behind cloudflared (Phase 48-0, item 1).

Through the tunnel every request comes from 127.0.0.1; CF-Connecting-IP
names the client. Two clients get two rate-limit buckets and their own IP in
login_attempts; a peer that is not cloudflared is not believed. v0.1.21 read
no CF-Connecting-IP: without uvicorn's proxy-headers step every client was
one bucket.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config.settings import settings

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"
BODY = {"username": "nobody-here", "password": "wrong-password"}


@pytest.fixture()
def limits_on():
    from app.middleware.rate_limit import limiter

    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def _from(ip: str) -> dict:
    return {"CF-Connecting-IP": ip}


def test_two_clients_two_buckets(client: TestClient, monkeypatch, limits_on):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1,testclient")
    limit = int(settings.RATE_LIMIT_LOGIN.split("/")[0])  # read when the route was decorated (30/minute)
    first = [client.post(LOGIN, json=BODY, headers=_from("203.0.113.1")).status_code for _ in range(limit + 1)]
    other = client.post(LOGIN, json=BODY, headers=_from("203.0.113.2")).status_code
    assert first[-1] == 429, first
    assert other == 401  # its own bucket: a wrong password, not 429


def test_login_attempts_keep_the_clients_ip(client: TestClient, session, monkeypatch):
    from app.db.models import LoginAttempt

    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1,testclient")
    client.post(LOGIN, json=BODY, headers=_from("203.0.113.7"))
    session.expire_all()
    ips = session.scalars(select(LoginAttempt.ip_address).where(LoginAttempt.username == BODY["username"])).all()
    assert ips == ["203.0.113.7"]


def test_another_peer_cannot_pick_its_bucket(client: TestClient, session):
    """Not cloudflared: CF-Connecting-IP is ignored, the peer is the IP."""
    from app.db.models import LoginAttempt

    client.post(LOGIN, json=BODY, headers=_from("203.0.113.8"))
    session.expire_all()
    ips = session.scalars(select(LoginAttempt.ip_address).where(LoginAttempt.username == BODY["username"])).all()
    assert ips == ["testclient"]
