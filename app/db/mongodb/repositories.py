"""MongoDB log repositories (data access layer).

All functions are fail-silent: they never raise and never interrupt the
business request. If MongoDB or the SSH tunnel is down they log the error
and return a neutral value.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo.errors import PyMongoError

from app.db.mongodb.client import get_database

logger = logging.getLogger(__name__)

USER_LOGS = "user_logs"
SEARCH_LOGS = "search_logs"
SYSTEM_EVENTS = "system_events"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# user_logs
# ---------------------------------------------------------------------------

def insert_user_log(
    user_id: str,
    action: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    db = get_database()
    if db is None:
        logger.warning("MongoDB unavailable - skipping user_log insert")
        return None
    try:
        doc = {
            "user_id": str(user_id),
            "action": action,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_id": request_id,
            "metadata": metadata or {},
            "created_at": _utcnow(),
        }
        result = db[USER_LOGS].insert_one(doc)
        return str(result.inserted_id)
    except PyMongoError as exc:
        logger.error("Insert user_log failed: %s", exc)
        return None


def query_user_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = get_database()
    if db is None:
        return []
    try:
        filter_: dict[str, Any] = {}
        if user_id:
            filter_["user_id"] = str(user_id)
        if action:
            filter_["action"] = action
        cursor = (
            db[USER_LOGS].find(filter_).sort("created_at", -1).skip(offset).limit(limit)
        )
        return list(cursor)
    except PyMongoError as exc:
        logger.error("Query user_logs failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# search_logs
# ---------------------------------------------------------------------------

def insert_search_log(
    user_id: str,
    query: str,
    filters: Optional[dict[str, Any]] = None,
    result_count: Optional[int] = None,
    request_id: Optional[str] = None,
) -> Optional[str]:
    db = get_database()
    if db is None:
        logger.warning("MongoDB unavailable - skipping search_log insert")
        return None
    try:
        doc = {
            "user_id": str(user_id),
            "query": query,
            "filters": filters or {},
            "result_count": result_count,
            "request_id": request_id,
            "created_at": _utcnow(),
        }
        result = db[SEARCH_LOGS].insert_one(doc)
        return str(result.inserted_id)
    except PyMongoError as exc:
        logger.error("Insert search_log failed: %s", exc)
        return None


def query_search_logs(
    user_id: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = get_database()
    if db is None:
        return []
    try:
        filter_: dict[str, Any] = {}
        if user_id:
            filter_["user_id"] = str(user_id)
        if query:
            filter_["query"] = {"$regex": query, "$options": "i"}
        cursor = (
            db[SEARCH_LOGS].find(filter_).sort("created_at", -1).skip(offset).limit(limit)
        )
        return list(cursor)
    except PyMongoError as exc:
        logger.error("Query search_logs failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# system_events
# ---------------------------------------------------------------------------

def insert_system_event(
    event_type: str,
    source: str,
    severity: str = "info",
    message: str = "",
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    db = get_database()
    if db is None:
        logger.warning("MongoDB unavailable - skipping system_event insert")
        return None
    try:
        doc = {
            "event_type": event_type,
            "source": source,
            "severity": severity,
            "message": message,
            "request_id": request_id,
            "metadata": metadata or {},
            "created_at": _utcnow(),
        }
        result = db[SYSTEM_EVENTS].insert_one(doc)
        return str(result.inserted_id)
    except PyMongoError as exc:
        logger.error("Insert system_event failed: %s", exc)
        return None


def query_system_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    db = get_database()
    if db is None:
        return []
    try:
        filter_: dict[str, Any] = {}
        if event_type:
            filter_["event_type"] = event_type
        if severity:
            filter_["severity"] = severity
        cursor = (
            db[SYSTEM_EVENTS]
            .find(filter_)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return list(cursor)
    except PyMongoError as exc:
        logger.error("Query system_events failed: %s", exc)
        return []