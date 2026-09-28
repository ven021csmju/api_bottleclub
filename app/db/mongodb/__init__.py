"""MongoDB log service for the Main Backend.

Used only for logs / search history / user activity / system events —
never for business data (users, products, orders, sales stay in PostgreSQL).

Public API:
    log_user_activity(...)
    log_search(...)
    log_system_event(...)
    get_mongodb_health()
    close_connection()
"""

from app.db.mongodb.client import (
    close_connection,
    get_database,
    get_mongodb_health,
)
from app.db.mongodb.service import (
    log_search,
    log_system_event,
    log_user_activity,
    sync_log_user_activity,
)

__all__ = [
    "close_connection",
    "get_database",
    "get_mongodb_health",
    "log_search",
    "log_system_event",
    "log_user_activity",
    "sync_log_user_activity",
]