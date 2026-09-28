"""Lazy, fail-silent MongoDB client manager for the Main Backend.

MongoDB stores only logs / search history / system events on the Ubuntu
server, reached from Windows through an SSH tunnel
(`ssh -L 27017:localhost:27017 user@server`).

Design rules:
- MongoDB must NEVER break a business request or block app startup.
- Connection is lazy: no I/O happens at import or startup time.
- After a failed connection we cool down before retrying, so a down
  tunnel does not slow down every request.
- All public callers must handle failures themselves (repositories and
  service layer already swallow errors).
"""

import logging
import time
from typing import Optional

from pymongo import ASCENDING
from pymongo.errors import (
    ConnectionFailure,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)
from pymongo.mongo_client import MongoClient

from app.config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_next_retry_at: float = 0.0


def _client_is_healthy(candidate: MongoClient) -> bool:
    """Ping the server. Cheap health probe that raises on failure."""
    candidate.admin.command("ping")
    return True


def _create_client() -> Optional[MongoClient]:
    """Build a client and verify connectivity. Returns None on failure."""
    global _client
    try:
        candidate = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=settings.MONGODB_CONNECTION_TIMEOUT_MS,
            maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
            minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
        )
        _client_is_healthy(candidate)
        _ensure_indexes(candidate[settings.MONGODB_DATABASE])
        _client = candidate
        logger.info(
            "MongoDB connected (db=%s host=%s)",
            settings.MONGODB_DATABASE,
            settings.MONGODB_URI,
        )
        return _client
    except (ConnectionFailure, ServerSelectionTimeoutError, OperationFailure, PyMongoError) as exc:
        logger.error("MongoDB connection failed: %s", exc)
        try:
            client_local = globals().get("_client")
            if client_local is not None:
                _client = None
                client_local.close()
        except PyMongoError:
            pass
        return None


def get_client() -> Optional[MongoClient]:
    """Return a connected client or None. Never raises."""
    global _client, _next_retry_at
    now = time.monotonic()
    if _client is None:
        if now < _next_retry_at:
            return None
        if _create_client() is None:
            _next_retry_at = now + settings.MONGODB_RETRY_COOLDOWN_SECONDS
            return None
    try:
        _client_is_healthy(_client)
        return _client
    except PyMongoError as exc:
        logger.error("MongoDB client unhealthy, recycling: %s", exc)
        try:
            _client.close()
        except PyMongoError:
            pass
        _client = None
        _next_retry_at = now + settings.MONGODB_RETRY_COOLDOWN_SECONDS
        return None


def get_database():
    """Return the MongoDB database or None if unavailable."""
    client = get_client()
    if client is None:
        return None
    return client[settings.MONGODB_DATABASE]


def get_mongodb_health() -> dict:
    """Report MongoDB status without raising. Does not touch Mongo until used."""
    if _client is None:
        return {
            "status": "disconnected",
            "database": settings.MONGODB_DATABASE,
            "uri": _safe_uri(settings.MONGODB_URI),
        }
    try:
        _client_is_healthy(_client)
        return {
            "status": "connected",
            "database": settings.MONGODB_DATABASE,
            "uri": _safe_uri(settings.MONGODB_URI),
        }
    except PyMongoError as exc:
        return {
            "status": "disconnected",
            "database": settings.MONGODB_DATABASE,
            "uri": _safe_uri(settings.MONGODB_URI),
            "error": str(exc),
        }


def close_connection() -> None:
    """Close the Mongo client. Safe to call multiple times / with None."""
    global _client
    if _client is not None:
        try:
            _client.close()
            logger.info("MongoDB connection closed")
        except PyMongoError as exc:
            logger.error("Error closing MongoDB connection: %s", exc)
        finally:
            _client = None


def _safe_uri(uri: str) -> str:
    """Mask credentials in a connection string for logging/health output."""
    if "://" not in uri or "@" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    if "@" in rest:
        creds, hostpart = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{hostpart}"
    return uri


def _ensure_indexes(db) -> None:
    """Create collections + indexes + TTL indexes (idempotent)."""
    user_logs = db["user_logs"]
    search_logs = db["search_logs"]
    system_events = db["system_events"]

    _create_ttl_index(
        user_logs,
        "created_at",
        settings.MONGODB_USER_LOGS_TTL_DAYS,
        "user_logs_ttl",
    )
    user_logs.create_index([("user_id", ASCENDING)])
    user_logs.create_index([("action", ASCENDING)])
    user_logs.create_index([("request_id", ASCENDING)])

    _create_ttl_index(
        search_logs,
        "created_at",
        settings.MONGODB_SEARCH_LOGS_TTL_DAYS,
        "search_logs_ttl",
    )
    search_logs.create_index([("user_id", ASCENDING)])
    search_logs.create_index([("query", ASCENDING)])

    _create_ttl_index(
        system_events,
        "created_at",
        settings.MONGODB_SYSTEM_EVENTS_TTL_DAYS,
        "system_events_ttl",
    )
    system_events.create_index([("event_type", ASCENDING)])
    system_events.create_index([("severity", ASCENDING)])
    system_events.create_index([("request_id", ASCENDING)])


def _create_ttl_index(collection, field: str, ttl_days: int, name: str) -> None:
    """Create a TTL index, dropping any plain index on the same field first."""
    for idx_name, idx in collection.index_information().items():
        keys = list(idx.get("key", []))
        if len(keys) == 1 and keys[0][0] == field and idx_name != "_id_":
            if "expireAfterSeconds" not in idx:
                logger.warning(
                    "Dropping non-TTL index %s on %s to replace with TTL index",
                    idx_name,
                    field,
                )
                collection.drop_index(idx_name)
    collection.create_index(
        [(field, ASCENDING)],
        expireAfterSeconds=ttl_days * 86400,
        name=name,
    )