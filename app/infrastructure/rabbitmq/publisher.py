import json
import logging
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message

from app.config.settings import settings
from app.infrastructure.rabbitmq.connection import create_connection

logger = logging.getLogger(__name__)


async def publish_user_log(event: dict[str, Any]) -> bool:
    """
    Publish a user log event to RabbitMQ.

    Returns:
        True  = message published successfully
        False = publish failed
    """

    connection = None

    try:
        connection = await create_connection()

        channel = await connection.channel(
            publisher_confirms=True
        )

        exchange = await channel.declare_exchange(
            settings.RABBITMQ_EXCHANGE,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )

        message = Message(
            body=json.dumps(
                event,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8"),
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=str(event.get("event_id", "")),
        )

        await exchange.publish(
            message,
            routing_key=settings.RABBITMQ_ROUTING_KEY,
            mandatory=True,
        )

        logger.info(
            "User log published to RabbitMQ: event_id=%s",
            event.get("event_id"),
        )

        return True

    except Exception:
        logger.exception(
            "Failed to publish user log to RabbitMQ"
        )
        return False

    finally:
        if connection and not connection.is_closed:
            await connection.close()
