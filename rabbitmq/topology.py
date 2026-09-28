"""RabbitMQ topology (Phase 4).

Declares the durable exchange, the user log queue and the dead-letter queue
that must survive broker restarts:

    user_logs (direct, durable)
        |
        +-- user.log      --> user_log_queue (durable)
        +-- user.log.dead --> user_log_dlq    (durable)

Idempotent: calling repeatedly with an existing topology is a no-op.
"""

import logging

import pika.adapters.blocking_connection

from app.config.settings import settings

logger = logging.getLogger(__name__)


def declare_topology(channel: "pika.adapters.blocking_connection.BlockingChannel") -> None:
    channel.exchange_declare(
        exchange=settings.RABBITMQ_EXCHANGE,
        exchange_type="direct",
        durable=True,
        auto_delete=False,
    )

    channel.queue_declare(
        queue=settings.RABBITMQ_QUEUE,
        durable=True,
        auto_delete=False,
    )
    channel.queue_bind(
        queue=settings.RABBITMQ_QUEUE,
        exchange=settings.RABBITMQ_EXCHANGE,
        routing_key=settings.RABBITMQ_ROUTING_KEY,
    )

    channel.queue_declare(
        queue=settings.RABBITMQ_DLQ,
        durable=True,
        auto_delete=False,
    )
    channel.queue_bind(
        queue=settings.RABBITMQ_DLQ,
        exchange=settings.RABBITMQ_EXCHANGE,
        routing_key=settings.RABBITMQ_DLQ_ROUTING_KEY,
    )

    logger.info(
        "RabbitMQ topology ensured: exchange=%s binding=%s->%s dlq=%s",
        settings.RABBITMQ_EXCHANGE,
        settings.RABBITMQ_ROUTING_KEY,
        settings.RABBITMQ_QUEUE,
        settings.RABBITMQ_DLQ,
    )