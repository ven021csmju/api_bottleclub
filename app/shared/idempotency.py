"""Idempotency keys for the routes that take money or stock (Phase 38b).

POST /orders/, POST /orders/{id}/checkout, POST /payments/ and POST /returns/
need an ``Idempotency-Key`` header (or, on the two order routes, the body's
``idempotency_key``); without one they answer 422 IDEMPOTENCY_KEY_REQUIRED.

A key is the user's, per route (``idempotency_keys``, unique per user, route
and key, migration 015) and is kept 24 hours:

- the same key with the same request (path, X-Branch-Id and body) gets the
  first answer again, unchanged, with ``Idempotent-Replayed: true``;
- the same key with a different request is 409 IDEMPOTENCY_KEY_REUSED;
- an error answer is not kept: the request can be sent again with its key.

Two requests with one key at the same moment run one after the other: a
PostgreSQL advisory lock on (user, route, key) is held on a connection of its
own for the whole request (the request's session commits midway, which would
end a transaction lock), so the second waits and then replays the first.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.models import IdempotencyKey
from app.shared.exceptions import AppException

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)
MAX_LENGTH = 255

#: Session-level: it outlives the request session's commits; released at the
#: end of the request (or when its connection closes).
LOCK_SQL = "SELECT pg_advisory_lock(:id)"
UNLOCK_SQL = "SELECT pg_advisory_unlock(:id)"

_lock_engines: dict[str, Engine] = {}


def _lock_engine(db: Session) -> Engine:
    """An engine without a pool for the lock connections, on the session's database:
    a lock held for a whole request never waits for, or starves, the request pool."""
    bind = db.get_bind()
    url = getattr(bind, "engine", bind).url
    key = url.render_as_string(hide_password=False)
    if key not in _lock_engines:
        _lock_engines[key] = create_engine(url, poolclass=NullPool)
    return _lock_engines[key]


def request_key(request: Request, body_key: str | None = None) -> str:
    header = request.headers.get(HEADER)
    header = header.strip() if header is not None else None
    if header and body_key and header != body_key:
        raise AppException(
            status_code=422,
            detail=f"{HEADER} and idempotency_key differ",
            code="IDEMPOTENCY_KEY_MISMATCH",
        )
    key = header or body_key
    if not key:
        raise AppException(
            status_code=422,
            detail=f"An {HEADER} header is required",
            code="IDEMPOTENCY_KEY_REQUIRED",
        )
    if len(key) > MAX_LENGTH:
        raise AppException(
            status_code=422,
            detail=f"{HEADER} is longer than {MAX_LENGTH} characters",
            code="VALIDATION_ERROR",
        )
    return key


def request_hash(request: Request, body: dict) -> str:
    canonical = json.dumps(
        {"path": request.url.path, "branch": request.headers.get("x-branch-id"), "body": body},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _lock_id(user_id: int, endpoint: str, key: str) -> int:
    digest = hashlib.sha256(f"{user_id}|{endpoint}|{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def run_idempotent(
    request: Request,
    db: Session,
    user_id: int,
    body: BaseModel,
    run: Callable[[], BaseModel],
    *,
    secret_fields: tuple[str, ...] = (),
) -> Any:
    """``run()`` once per (user, route, key); its answer is kept and replayed.
    ``secret_fields`` are kept as null (a tracking token is shown once only)."""
    body_key = getattr(body, "idempotency_key", None)
    key = request_key(request, body_key)
    endpoint = f"{request.method} {request.scope['route'].path}"
    digest = request_hash(request, body.model_dump(mode="json", exclude={"idempotency_key"}))
    lock_id = _lock_id(user_id, endpoint, key)

    with _lock_engine(db).connect() as lock:
        lock.execute(text(LOCK_SQL), {"id": lock_id})
        try:
            now = datetime.now(timezone.utc)
            db.execute(delete(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id, IdempotencyKey.expires_at <= now))
            db.commit()
            kept = db.scalars(select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.idempotency_key == key,
            )).first()
            if kept is not None:
                if kept.request_hash != digest:
                    raise AppException(
                        status_code=409,
                        detail="This Idempotency-Key was used for a different request",
                        code="IDEMPOTENCY_KEY_REUSED",
                    )
                return JSONResponse(
                    status_code=kept.response_status,
                    content=kept.response_body,
                    headers={"Idempotent-Replayed": "true"},
                )

            result = run()
            answer = result.model_dump(mode="json", by_alias=True)
            for field in secret_fields:
                if field in answer:
                    answer[field] = None
            db.add(IdempotencyKey(
                idempotency_key=key,
                user_id=user_id,
                endpoint=endpoint,
                request_hash=digest,
                response_status=200,
                response_body=answer,
                expires_at=now + TTL,
            ))
            db.commit()
            return result
        finally:
            lock.execute(text(UNLOCK_SQL), {"id": lock_id})
            lock.commit()
