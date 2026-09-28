"""User-log event publishing (Phase 5).

Thin helpers that let business services publish user-activity events into the
RabbitMQ pipeline without coupling to pika. The Phase 4 publisher contract is
preserved: publish NEVER raises, so a down RabbitMQ cannot break the business
operation.

Two entry points:

- ``publish_user_event`` (async) - await from async routers/services
  (e.g. the slip-verify upload flow).
- ``publish_user_event_sync`` (sync) - safe to call from sync FastAPI
  endpoints; Starlette runs those in a worker thread, so the private event
  loop created by ``asyncio.run`` never collides with a running loop.

Envelope conventions (see ``rabbitmq/schemas.py``):
- ``event_id`` = a fresh UUID per event.
- ``version`` = 1, ``source`` = "bottleclub-api".
- ``user_id`` comes from the authenticated user, ``request_id`` is carried
  through from the correlation middleware on ``request.state.request_id``.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from rabbitmq.publisher import publish_user_log
from rabbitmq.schemas import UserLogEvent

logger = logging.getLogger(__name__)

EVENT_SOURCE = "bottleclub-api"
EVENT_VERSION = 1


def new_event_id() -> str:
    return str(uuid.uuid4())


def build_user_event(
    event_type: str,
    user_id: Any,
    request_id: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> UserLogEvent:
    """Build a validated envelope. Raises if data contains sensitive keys."""
    return UserLogEvent(
        event_id=new_event_id(),
        event_type=event_type,
        version=EVENT_VERSION,
        source=EVENT_SOURCE,
        user_id=str(user_id),
        request_id=request_id or "",
        timestamp=datetime.now(timezone.utc),
        data=data or {},
    )


async def publish_user_event(
    event_type: str,
    user_id: Any,
    request_id: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Publish an event from an async context. Failure is fully isolated."""
    try:
        await publish_user_log(build_user_event(event_type, user_id, request_id, data))
    except Exception as exc:  # noqa: BLE001 - must never escape to the caller
        logger.error(
            "user_event_unexpected_failure event_type=%s user_id=%s error=%s",
            event_type,
            user_id,
            exc,
        )


def publish_user_event_sync(
    event_type: str,
    user_id: Any,
    request_id: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Publish an event from a sync context. Failure is fully isolated."""
    try:
        asyncio.run(publish_user_log(build_user_event(event_type, user_id, request_id, data)))
    except Exception as exc:  # noqa: BLE001 - must never escape to the caller
        logger.error(
            "user_event_unexpected_failure event_type=%s user_id=%s error=%s",
            event_type,
            user_id,
            exc,
        )