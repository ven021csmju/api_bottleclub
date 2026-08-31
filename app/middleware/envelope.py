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
RAW_PREFIXES: tuple[str, ...] = ("/health", "/openapi.json", "/docs", "/redoc")

PAGINATION_KEYS = ("page", "per_page", "total")


def should_use_envelope(path: str) -> bool:
    return not path.startswith(RAW_PREFIXES)


def build_envelope(data: Any, meta: dict | None = None, request_id: str = "") -> dict:
    return {"data": data, "meta": meta, "request_id": request_id}


def extract_meta(payload: dict) -> tuple[Any, dict | None]:
    if set(PAGINATION_KEYS).issubset(payload.keys()):
        meta = {key: payload[key] for key in PAGINATION_KEYS}
        data = {k: v for k, v in payload.items() if k not in PAGINATION_KEYS}
        return data, meta
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

        _headers = {k: v for k, v in response.headers.items()}
        _headers.pop("content-length", None)
        _headers.pop("transfer-encoding", None)
        wrapped = JSONResponse(
            content=build_envelope(data, meta, request_id),
            status_code=response.status_code,
            headers=_headers,
        )
        return wrapped


def _rebuild_response(
    response: Response,
    body: bytes,
    headers: dict | None = None,
) -> Response:
    """Return a streaming response with ``body`` re-attached.

    ``BaseHTTPMiddleware`` wraps the downstream response in a stream, so once
    ``body_iterator`` is consumed it cannot be replayed. Re-serve the bytes via
    a fresh ``StreamingResponse`` instead of returning the original response,
    which would otherwise yield an empty stream to the caller.
    """
    _headers = {k: v for k, v in response.headers.items()}
    if headers:
        _headers.update(headers)
    _headers.pop("content-length", None)
    _headers.pop("transfer-encoding", None)
    return StreamingResponse(iter([body]), status_code=response.status_code, headers=_headers)