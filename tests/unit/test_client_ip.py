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


# Phase 49 item 2: a peer in Cloudflare's ranges (a proxied DNS record instead
# of the tunnel) gives CF-Connecting-IP only; resolve_client_ip is the one
# function behind the rate limits, login_attempts and the audit log.
import asyncio  # noqa: E402

from app.config.cloudflare_ips import CLOUDFLARE_IP_RANGES_DEFAULT, _networks  # noqa: E402
from app.middleware.client_ip import client_ip, rate_limit_key, resolve_client_ip  # noqa: E402

CF_V4 = "172.68.10.20"      # in 172.64.0.0/13
CF_V6 = "2606:4700:10::1"   # in 2606:4700::/32


def _h(**values) -> dict:
    return {k.replace("_", "-").lower().encode(): v.encode() for k, v in values.items()}


@pytest.mark.parametrize("peer", [CF_V4, CF_V6, f"::ffff:{CF_V4}"])
def test_a_cloudflare_peer_gives_cf_connecting_ip(peer):
    assert resolve_client_ip(peer, _h(CF_Connecting_IP="203.0.113.9")) == ("203.0.113.9", True)
    assert resolve_client_ip(peer, _h(CF_Connecting_IP="2001:DB8::7")) == ("2001:db8::7", True)


def test_a_cloudflare_peer_never_gives_forwarded_for():
    """Cloudflare appends to what the client sent: only CF-Connecting-IP is its own."""
    assert resolve_client_ip(CF_V4, _h(X_Forwarded_For="6.6.6.6")) == (CF_V4, True)
    assert resolve_client_ip(CF_V4, _h(CF_Connecting_IP="garbage", X_Forwarded_For="6.6.6.6")) == (CF_V4, True)


@pytest.mark.parametrize("peer", ["198.51.100.20", "2001:db8::20", "172.63.255.255", "2606:4701::1"])
def test_another_peer_cannot_forge_the_headers(peer):
    """Straight to the origin with made-up headers: the peer is the client."""
    headers = _h(CF_Connecting_IP="203.0.113.9", X_Forwarded_For="203.0.113.9", X_Forwarded_Proto="https")
    assert resolve_client_ip(peer, headers) == (peer, False)


@pytest.mark.parametrize("peer", [CF_V4, CF_V6, "198.51.100.20", "2001:db8::20"])
def test_no_header_is_the_peer(peer):
    assert resolve_client_ip(peer, {})[0] == peer


def test_no_peer_is_none():
    assert resolve_client_ip(None, _h(CF_Connecting_IP="203.0.113.9")) == (None, False)


def test_the_middleware_sets_the_client_for_a_cloudflare_peer():
    seen = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"], scheme=scope["scheme"], state=scope["state"])

    scope = {"type": "http", "client": (CF_V6, 443), "scheme": "http",
             "headers": list(_h(CF_Connecting_IP="203.0.113.9", X_Forwarded_Proto="https").items())}
    asyncio.run(ClientIPMiddleware(app)(scope, None, None))
    assert seen == {"client": ("203.0.113.9", 0), "scheme": "https", "state": {"client_ip": "203.0.113.9"}}


def test_client_ip_and_the_rate_limit_key_read_it():
    from starlette.requests import Request as StarletteRequest

    request = StarletteRequest({"type": "http", "client": ("203.0.113.9", 0), "headers": [],
                                "state": {"client_ip": "203.0.113.9"}})
    assert client_ip(request) == rate_limit_key(request) == "203.0.113.9"
    bare = StarletteRequest({"type": "http", "client": None, "headers": []})
    assert client_ip(bare) is None and rate_limit_key(bare) == "unknown"


def test_the_ranges_are_configurable(tmp_path, monkeypatch):
    assert len(_networks("", "")) == len(CLOUDFLARE_IP_RANGES_DEFAULT) == 22
    monkeypatch.setattr(settings, "CLOUDFLARE_IP_RANGES", "198.51.100.0/24, 2001:db8::/32")
    monkeypatch.setattr(settings, "CLOUDFLARE_IP_RANGES_FILE", "")
    assert resolve_client_ip("198.51.100.20", _h(CF_Connecting_IP="203.0.113.9"))[0] == "203.0.113.9"
    assert resolve_client_ip(CF_V4, _h(CF_Connecting_IP="203.0.113.9"))[0] == CF_V4  # no longer Cloudflare's
    ranges = tmp_path / "cf.txt"
    ranges.write_text("# Cloudflare\n203.0.113.0/24\n\n")
    monkeypatch.setattr(settings, "CLOUDFLARE_IP_RANGES_FILE", str(ranges))  # the file wins
    assert resolve_client_ip("203.0.113.1", _h(CF_Connecting_IP="192.0.2.5"))[0] == "192.0.2.5"


@pytest.mark.parametrize("ranges", ["not-a-cidr", "10.0.0.1/8", ","])
def test_bad_ranges_stop_the_start(ranges):
    from pydantic import ValidationError

    from app.config.settings import Settings

    with pytest.raises(ValidationError, match="CLOUDFLARE_IP_RANGES"):
        Settings(CLOUDFLARE_IP_RANGES=ranges)
