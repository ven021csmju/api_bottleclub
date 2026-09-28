"""RabbitMQ user-log publisher (Phase 4).

Failure isolation is the primary contract: ``publish_user_log`` NEVER raises.
If RabbitMQ is unavailable the business operation must continue unaffected -
the function logs a structured ``user_log_publish_failed`` record and returns
a ``PublishResult`` with ``success=False``.

Implementation notes (reuse existing conventions):

- The blocking pika I/O runs in a threadpool via ``run_in_threadpool`` exactly
  like the existing blocking MongoDB operations.
- The connection is created lazily on first publish and reused; after an
  operational failure it is dropped so the next publish tries again.
- Messages are published with ``delivery_mode=2`` (persistent) and publisher
  confirms are enabled so success reflects a broker acknowledgment.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import pika
from starlette.concurrency import run_in_threadpool

from app.config.settings import settings
from rabbitmq import connection as rabbit_connection
from rabbitmq.schemas import UserLogEvent
from rabbitmq.topology import declare_topology

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CONNECTION: Optional[pika.BlockingConnection] = None
_CHANNEL: Optional[pika.channel.Channel] = None
_TOPOLOGY_SIG: Optional[tuple] = None


@dataclass
class PublishResult:
    success: bool
    request_id: Optional[str] = None
    message: str = ""


def _close_locked() -> None:
    global _CONNECTION, _CHANNEL, _TOPOLOGY_SIG
    if _CHANNEL is not None:
        try:
            if _CHANNEL.is_open:
                _CHANNEL.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing RabbitMQ publisher channel: %s", exc)
    _CHANNEL = None
    if _CONNECTION is not None:
        try:
            if _CONNECTION.is_open:
                _CONNECTION.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing RabbitMQ publisher connection: %s", exc)
    _CONNECTION = None
    _TOPOLOGY_SIG = None


def close() -> None:
    """Drop the cached publisher connection (used on shutdown / tests)."""
    with _LOCK:
        _close_locked()


def reportable_error(exc: Exception) -> str:
    """Return an error message that never includes credentials/URL passwords."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _publish_sync(event: UserLogEvent) -> PublishResult:
    """Blocking publish executed from the threadpool (never leaks exceptions)."""
    global _CONNECTION, _CHANNEL, _TOPOLOGY_SIG
    try:
        body = event.model_dump_json()
        sig = (
            settings.RABBITMQ_EXCHANGE,
            settings.RABBITMQ_ROUTING_KEY,
            settings.RABBITMQ_QUEUE,
            settings.RABBITMQ_DLQ,
        )
        with _LOCK:
            if _TOPOLOGY_SIG != sig:
                _close_locked()
            if _CHANNEL is None or _CHANNEL.is_closed or not _CHANNEL.is_open:
                if _CONNECTION is None or _CONNECTION.is_closed:
                    _CONNECTION = rabbit_connection.create_blocking_connection()
                _CHANNEL = _CONNECTION.channel()
                declare_topology(_CHANNEL)
                _CHANNEL.confirm_delivery()
                _TOPOLOGY_SIG = sig
            channel = _CHANNEL

            # confirm_delivery() turns basic_publish into a blocking call that
            # returns only after the broker acknowledges; failures raise
            # (UnroutableError, NackError, ChannelClosedByBroker, ...).
            channel.basic_publish(
                exchange=settings.RABBITMQ_EXCHANGE,
                routing_key=settings.RABBITMQ_ROUTING_KEY,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                    message_id=event.event_id,
                    timestamp=int(time.time()),
                    headers={"event_id": event.event_id, "request_id": event.request_id},
                ),
                mandatory=True,
            )

        logger.info(
            "user_log_published event_id=%s request_id=%s event_type=%s source=%s user_id=%s",
            event.event_id,
            event.request_id,
            event.event_type,
            event.source,
            event.user_id,
        )
        return PublishResult(success=True, request_id=event.request_id, message="published")
    except Exception as exc:  # noqa: BLE001 - failure must never propagate to the caller
        with _LOCK:
            _close_locked()
        logger.error(
            "user_log_publish_failed event_id=%(event_id)s request_id=%(request_id)s "
            "event_type=%(event_type)s error=%(error)s",
            {**event.safe_log_fields(), "error": reportable_error(exc)},
        )
        return PublishResult(
            success=False,
            request_id=event.request_id,
            message="RabbitMQ publish failed",
        )


async def publish_user_log(event: Any) -> PublishResult:
    """Publish a user-log event.

    Accepts a ``UserLogEvent`` or a plain dict payload. Never raises - on any
    failure (including schema validation of a bad envelope) it returns a
    ``PublishResult`` with ``success=False`` so the caller's business logic
    can continue unaffected.
    """
    try:
        if isinstance(event, UserLogEvent):
            parsed = event
        else:
            parsed = UserLogEvent.model_validate(event)
        return await run_in_threadpool(_publish_sync, parsed)
    except Exception as exc:  # noqa: BLE001
        logger.error("user_log_publish_failed error=%s", reportable_error(exc))
        return PublishResult(success=False, message="event validation failed")