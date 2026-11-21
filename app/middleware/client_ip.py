"""The client's IP (Phase 48-0, Phase 49 item 2): one function for every
rate limit, login_attempts and the audit log.

Production listens on 127.0.0.1 only and is reached through Cloudflare
Tunnel: the TCP peer is cloudflared, the client is in the headers.
``resolve_client_ip(peer, headers)``:

- a peer of TRUSTED_PROXY_IPS (cloudflared on this host):
  ``CF-Connecting-IP`` when it is a well-formed IP, else the right-most
  ``X-Forwarded-For`` entry that is not a trusted proxy (what uvicorn
  --proxy-headers did);
- a peer in Cloudflare's ranges (``cloudflare_networks()``: the origin is
  reached through a proxied DNS record, not the tunnel): ``CF-Connecting-IP``
  only, which Cloudflare's edge always overwrites (X-Forwarded-For keeps what
  the client sent);
- any other peer: its own address. Its headers are not believed, so a client
  that reaches the origin directly cannot pick another client's bucket.

``X-Forwarded-Proto`` sets the scheme for the same peers.
``ClientIPMiddleware`` puts the result in ``request.client`` and
``request.state.client_ip``; ``client_ip(request)`` reads it.

uvicorn must run with ``--no-proxy-headers``: its own proxy-headers step runs
before the app and replaces the peer, so the app could no longer tell
cloudflared from a client (``--forwarded-allow-ips="*"`` would believe anyone).
With uvicorn's step still on, the peer seen here is its X-Forwarded-For
result, not trusted, and kept: the same address as before this middleware.
"""
from __future__ import annotations

import ipaddress

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import settings
from app.config.cloudflare_ips import _networks


def cloudflare_networks() -> tuple:
    return _networks(settings.CLOUDFLARE_IP_RANGES, settings.CLOUDFLARE_IP_RANGES_FILE)


def well_formed_ip(value: str) -> str | None:
    """The IP in canonical form, or None (garbage, a port, a list)."""
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return str(mapped or ip)


def in_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    addr = getattr(addr, "ipv4_mapped", None) or addr
    return any(addr.version == net.version and addr in net for net in cloudflare_networks())


def client_from_headers(headers: dict[bytes, bytes], trusted: set[str]) -> str | None:
    cf = headers.get(b"cf-connecting-ip")
    if cf is not None:
        ip = well_formed_ip(cf.decode("latin1"))
        if ip is not None:
            return ip
    xff = headers.get(b"x-forwarded-for")
    if xff is not None:
        for entry in reversed(xff.decode("latin1").split(",")):
            ip = well_formed_ip(entry)
            if ip is not None and ip not in trusted:
                return ip
    return None


def resolve_client_ip(peer: str | None, headers: dict[bytes, bytes]) -> tuple[str | None, bool]:
    """(the client's IP, whether the peer's forwarding headers are believed)."""
    if peer is None:
        return None, False
    if peer in settings.trusted_proxy_ips:
        return client_from_headers(headers, settings.trusted_proxy_ips) or peer, True
    if in_cloudflare(peer):
        cf = headers.get(b"cf-connecting-ip")
        ip = well_formed_ip(cf.decode("latin1")) if cf is not None else None
        return ip or (well_formed_ip(peer) or peer), True
    return well_formed_ip(peer) or peer, False


def client_ip(request: Request) -> str | None:
    """The client's IP of a request (None: no peer). Rate-limit key too."""
    resolved = getattr(request.state, "client_ip", None)
    if resolved is not None:
        return resolved
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, dict(request.scope.get("headers") or []))[0]


def rate_limit_key(request: Request) -> str:
    return client_ip(request) or "unknown"


class ClientIPMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            peer = scope.get("client")
            headers = dict(scope["headers"])
            ip, believed = resolve_client_ip(peer[0] if peer else None, headers)
            scope = dict(scope)
            scope["state"] = {**scope.get("state", {}), "client_ip": ip}
            if peer is not None and ip != peer[0]:
                scope["client"] = (ip, 0)
            if believed:
                proto = headers.get(b"x-forwarded-proto", b"").decode("latin1").strip().lower()
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else proto.replace("http", "ws")
        await self.app(scope, receive, send)
