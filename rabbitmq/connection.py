"""RabbitMQ connection helpers (Phase 4).

Creates a pika ``BlockingConnection`` from the configured URL. The URL may
contain credentials - a redacted copy is used for any log output so the
password is never printed.

Connection-level retries are bounded (pika ``connection_attempts`` /
``retry_delay``) so a down broker fails fast instead of hanging a request
worker indefinitely.
"""

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse

import pika

from app.config.settings import settings

logger = logging.getLogger(__name__)


def redact_rabbitmq_url(url: Optional[str]) -> Optional[str]:
    """Remove the password component from an AMQP URL for safe logging."""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if "@" in parsed.netloc:
            userinfo, host = parsed.netloc.rsplit("@", 1)
            user = userinfo.split(":", 1)[0]
            return urlunparse(parsed._replace(netloc=f"{user}:***@{host}"))
    except Exception:
        pass
    return url


def url_redacted() -> Optional[str]:
    return redact_rabbitmq_url(settings.RABBITMQ_URL)


def build_connection_parameters():
    """Return pika connection parameters parsed from RABBITMQ_URL."""
    parameters = pika.URLParameters(settings.RABBITMQ_URL)
    parameters.connection_attempts = 2
    parameters.retry_delay = 1
    parameters.heartbeat = 60
    parameters.blocked_connection_timeout = 10
    return parameters


def create_blocking_connection() -> pika.BlockingConnection:
    """Open a blocking connection. Raises pika.exceptions.AMQPConnectionError on failure."""
    return pika.BlockingConnection(build_connection_parameters())


def close_connection(connection: Optional[pika.BlockingConnection]) -> None:
    """Safely close a connection, swallowing errors."""
    if connection is not None and connection.is_open:
        try:
            connection.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must never raise
            logger.debug("Error closing RabbitMQ connection: %s", exc)