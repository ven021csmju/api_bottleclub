"""Standard API response envelope.

Wraps successful JSON responses into the contract format::

    {"data": ..., "meta": ..., "request_id": "..."}

Error responses (status >= 400), non-JSON payloads, 204/HEAD/OPTIONS and a
small set of infrastructure paths (health, OpenAPI docs) are left untouched.
Legacy-compat routes (future) can be opted out via ``RAW_PATHS`` prefixes.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

#: Prefixes that always return raw payloads (backward/extra compat).
RAW_PREFIXES: tuple[str, ...] = (
    "/health",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/api/promotions",
    "/api/admin/promotions",
)

PAGINATION_KEYS = ("page", "per_page", "total")


def should_use_envelope(path: str) -> bool:
    return not path.startswith(RAW_PREFIXES)


def build_envelope(data: Any, meta: dict | None = None, request_id: str = "") -> dict:
    return {"data": data, "meta": meta, "request_id": request_id}


def extract_meta(payload: dict) -> tuple[Any, dict | None]:
    if set(PAGINATION_KEYS).issubset(payload.keys()):
        meta = {key: payload[key] for key in PAGINATION_KEYS}
        # Keep pagination in data for clients whose list contract exposes it
        # alongside the collection, while retaining meta for the envelope
        # contract and existing clients.
        return payload, meta
    return payload, None


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        if request.method in ("HEAD", "OPTIONS"):
            return response
        if response.status_code < 200 or response.status_code >= 300:
            return response

        path = request.url.path
        if not should_use_envelope(path):
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        try:
            body = b"".join([chunk async for chunk in response.body_iterator])
        except Exception:
            return response
        if not body:
            return response

        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return response

        # Already enveloped (e.g. handler already emitted a contract body).
        if isinstance(payload, dict) and "request_id" in payload:
            if "data" in payload or "detail" in payload:
                return _rebuild_response(response, body)

        request_id = (
            getattr(request.state, "request_id", "")
            or response.headers.get("X-Request-Id", "")
        )

        if isinstance(payload, dict):
            data, meta = extract_meta(payload)
        else:
            data, meta = payload, None

        wrapped = JSONResponse(
            content=build_envelope(data, meta, request_id),
            status_code=response.status_code,
        )
        return _with_headers_of(response, wrapped)


#: Headers of the downstream response the rebuilt one does not take over.
_LENGTH_HEADERS = (b"content-length", b"transfer-encoding")


def _with_headers_of(source: Response, target: Response) -> Response:
    """``target`` with every header of ``source`` but its length. Raw headers,
    not a dict: a dict would keep one ``Set-Cookie`` of several (Phase 45)."""
    target.raw_headers = [h for h in target.raw_headers if h[0] == b"content-length"] + [
        h for h in source.raw_headers if h[0].lower() not in _LENGTH_HEADERS
    ]
    return target


def _rebuild_response(response: Response, body: bytes) -> Response:
    """Return a streaming response with ``body`` re-attached.

    ``BaseHTTPMiddleware`` wraps the downstream response in a stream, so once
    ``body_iterator`` is consumed it cannot be replayed. Re-serve the bytes via
    a fresh ``StreamingResponse`` instead of returning the original response,
    which would otherwise yield an empty stream to the caller.
    """
    return _with_headers_of(response, StreamingResponse(iter([body]), status_code=response.status_code))
