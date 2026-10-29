"""The client's IP behind cloudflared (Phase 48-0).

Production listens on 127.0.0.1 only and is reached through Cloudflare
Tunnel: the TCP peer is cloudflared (127.0.0.1), the client is in the
headers. For a peer of TRUSTED_PROXY_IPS only:

- ``CF-Connecting-IP`` (set by Cloudflare's edge) when it is a well-formed IP;
- else the right-most ``X-Forwarded-For`` entry that is not a trusted proxy
  (what uvicorn --proxy-headers did);
- ``X-Forwarded-Proto`` sets the scheme.

Any other peer keeps its own address and scheme: its headers are not
believed. Everything that reads ``request.client.host`` (the rate limits,
login_attempts, the audit log) gets the result.

uvicorn must run with ``--no-proxy-headers``: its own proxy-headers step runs
before the app and replaces the peer, so the app could no longer tell
cloudflared from a client. With uvicorn's step still on, the peer seen here
is its X-Forwarded-For result, not trusted, and kept: the same address as
before this middleware.
"""
from __future__ import annotations

import ipaddress

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import settings


def well_formed_ip(value: str) -> str | None:
    """The IP in canonical form, or None (garbage, a port, a list)."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


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


class ClientIPMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            peer = scope.get("client")
            trusted = settings.trusted_proxy_ips
            if peer is not None and peer[0] in trusted:
                headers = dict(scope["headers"])
                scope = dict(scope)
                ip = client_from_headers(headers, trusted)
                if ip is not None:
                    scope["client"] = (ip, 0)
                proto = headers.get(b"x-forwarded-proto", b"").decode("latin1").strip().lower()
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else proto.replace("http", "ws")
        await self.app(scope, receive, send)
