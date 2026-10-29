"""The client's IP behind cloudflared (Phase 48-0, item 1).

Only a peer of TRUSTED_PROXY_IPS (cloudflared on 127.0.0.1) is believed:
CF-Connecting-IP when it is a well-formed IP, else the right-most
X-Forwarded-For entry that is not a proxy. Any other peer keeps its own
address whatever it sends. v0.1.21 read no CF-Connecting-IP and believed
what uvicorn's proxy-headers step gave it.
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.middleware.client_ip import ClientIPMiddleware, well_formed_ip

PEER = "testclient"  # TestClient's peer address


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ClientIPMiddleware)

    @app.get("/who")
    def who(request: Request) -> dict:
        return {"ip": request.client.host, "scheme": request.url.scheme}

    return app


def _who(headers: dict) -> dict:
    return TestClient(_app()).get("/who", headers=headers).json()


@pytest.fixture()
def behind_cloudflared(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", f"127.0.0.1,::1,{PEER}")


@pytest.mark.parametrize("headers", [
    {"CF-Connecting-IP": "203.0.113.9"},
    {"X-Forwarded-For": "203.0.113.9"},
    {"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.7", "X-Forwarded-Proto": "https"},
])
def test_another_peer_is_not_believed(headers):
    """Case 1: a peer that is not cloudflared sends a made-up CF-Connecting-IP."""
    assert _who(headers) == {"ip": PEER, "scheme": "http"}


def test_cloudflared_gives_the_client(behind_cloudflared):
    """Case 2: through the tunnel, each client is its own IP."""
    assert _who({"CF-Connecting-IP": "203.0.113.9"})["ip"] == "203.0.113.9"
    assert _who({"CF-Connecting-IP": "2001:db8::1"})["ip"] == "2001:db8::1"
    assert _who({"CF-Connecting-IP": " 2001:DB8:0::1 "})["ip"] == "2001:db8::1"  # canonical form


def test_no_header_is_as_before(behind_cloudflared):
    """Case 3: nothing sent, the peer stays (local scripts, health checks)."""
    assert _who({}) == {"ip": PEER, "scheme": "http"}


@pytest.mark.parametrize("cf", ["evil", "203.0.113.9:443", "203.0.113.9, 198.51.100.7", "", "999.1.1.1"])
def test_a_malformed_cf_header_falls_back_to_forwarded_for(behind_cloudflared, cf):
    assert _who({"CF-Connecting-IP": cf, "X-Forwarded-For": "1.2.3.4, 198.51.100.7"})["ip"] == "198.51.100.7"
    assert _who({"CF-Connecting-IP": cf})["ip"] == PEER


def test_forwarded_for_skips_proxies_and_garbage(behind_cloudflared):
    # A client's own X-Forwarded-For comes first; Cloudflare appends the address it saw.
    assert _who({"X-Forwarded-For": "6.6.6.6, 198.51.100.7, 127.0.0.1"})["ip"] == "198.51.100.7"
    assert _who({"X-Forwarded-For": "198.51.100.7, garbage"})["ip"] == "198.51.100.7"


def test_the_scheme_from_cloudflared(behind_cloudflared):
    assert _who({"X-Forwarded-Proto": "https"})["scheme"] == "https"
    assert _who({"X-Forwarded-Proto": "gopher"})["scheme"] == "http"


def test_well_formed_ip():
    assert well_formed_ip("10.0.0.1") == "10.0.0.1"
    assert well_formed_ip("10.0.0.1/24") is None


def test_the_app_puts_it_outermost():
    from app.main import create_app

    app = create_app()
    assert app.user_middleware[0].cls is ClientIPMiddleware
