"""High-level MongoDB logging service.

Public interface used from the Main Backend business logic.

All functions are fail-silent: exceptions are caught and logged, and the
business request continues normally when MongoDB / the SSH tunnel is down.
The `sync_*` variants are safe to pass to FastAPI BackgroundTasks.
"""

import logging
from typing import Any, Optional

from app.db.mongodb import repositories

logger = logging.getLogger(__name__)


async def log_user_activity(
    user_id: str,
    action: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Log a user activity. Returns inserted id, or None when logging fails."""
    try:
        return repositories.insert_user_log(
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - must never break business flow
        logger.error("log_user_activity failed: %s", exc)
        return None


async def log_search(
    user_id: str,
    query: str,
    filters: Optional[dict[str, Any]] = None,
    result_count: Optional[int] = None,
    request_id: Optional[str] = None,
) -> Optional[str]:
    """Log a search. Returns inserted id, or None when logging fails."""
    try:
        return repositories.insert_search_log(
            user_id=user_id,
            query=query,
            filters=filters,
            result_count=result_count,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001 - must never break business flow
        logger.error("log_search failed: %s", exc)
        return None


async def log_system_event(
    event_type: str,
    source: str,
    severity: str = "info",
    message: str = "",
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Log a system event. Returns inserted id, or None when logging fails."""
    try:
        return repositories.insert_system_event(
            event_type=event_type,
            source=source,
            severity=severity,
            message=message,
            request_id=request_id,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - must never break business flow
        logger.error("log_system_event failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Sync wrappers for FastAPI BackgroundTasks
# ---------------------------------------------------------------------------

def sync_log_user_activity(
    user_id: str,
    action: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    try:
        return repositories.insert_user_log(
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - must never break business flow
        logger.error("sync_log_user_activity failed: %s", exc)
        return None