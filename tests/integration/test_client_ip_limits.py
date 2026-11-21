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


# Phase 49 item 2: a peer in Cloudflare's ranges (a proxied DNS record instead
# of the tunnel) gives CF-Connecting-IP; any other peer is its own bucket.
CF_PEER = "172.68.10.20"  # in 172.64.0.0/13 (www.cloudflare.com/ips)


@pytest.fixture()
def peer_client(session):
    """A TestClient whose TCP peer is chosen (TestClient's is "testclient")."""
    from app.db.session import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield session)
    peer = {"ip": CF_PEER}

    async def from_peer(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (peer["ip"], 443)}
        await app(scope, receive, send)

    with TestClient(from_peer, raise_server_exceptions=False) as c:
        c.peer = peer
        yield c


def _attempt_ips(session) -> list[str]:
    from app.db.models import LoginAttempt

    session.expire_all()
    return session.scalars(select(LoginAttempt.ip_address).where(LoginAttempt.username == BODY["username"])
                           .order_by(LoginAttempt.id)).all()


@pytest.mark.parametrize("peer", [CF_PEER, "2606:4700:10::1"])
def test_two_clients_through_one_cloudflare_peer_two_buckets(peer_client, session, limits_on, peer):
    peer_client.peer["ip"] = peer
    limit = int(settings.RATE_LIMIT_LOGIN.split("/")[0])
    first = [peer_client.post(LOGIN, json=BODY, headers=_from("203.0.113.1")).status_code
             for _ in range(limit + 1)]
    other = peer_client.post(LOGIN, json=BODY, headers=_from("2001:db8::2")).status_code
    assert first[-1] == 429 and other == 401
    assert set(_attempt_ips(session)) == {"203.0.113.1", "2001:db8::2"}


def test_forged_headers_from_another_peer_are_one_bucket(peer_client, session, limits_on):
    """Straight to the origin: a new CF-Connecting-IP each time is still the peer."""
    peer_client.peer["ip"] = "198.51.100.20"
    limit = int(settings.RATE_LIMIT_LOGIN.split("/")[0])
    answers = [peer_client.post(LOGIN, json=BODY, headers={**_from(f"203.0.113.{i}"),
                                                           "X-Forwarded-For": f"203.0.113.{i}"}).status_code
               for i in range(1, limit + 2)]
    assert answers[-1] == 429
    assert set(_attempt_ips(session)) == {"198.51.100.20"}


def test_a_cloudflare_peer_without_the_header_is_itself(peer_client, session):
    peer_client.post(LOGIN, json=BODY)
    assert _attempt_ips(session) == [CF_PEER]


def test_public_track_through_cloudflare_counts_per_client(peer_client, limits_on):
    track = "/api/v1/orders/track"
    body = {"ref": "ORD-NONE-0001", "contact": "0899999999"}
    limit = int(settings.RATE_LIMIT_ORDER_TRACK_PUBLIC.split("/")[0])
    first = [peer_client.post(track, json=body, headers=_from("203.0.113.1")).status_code for _ in range(limit + 1)]
    assert first[-1] == 429
    assert peer_client.post(track, json=body, headers=_from("203.0.113.2")).status_code == 404
