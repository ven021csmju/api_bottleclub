import logging

import aio_pika

from app.config.settings import settings

logger = logging.getLogger(__name__)


async def create_connection() -> aio_pika.abc.AbstractRobustConnection:
    """Create a robust asynchronous RabbitMQ connection."""
    connection = await aio_pika.connect_robust(
        settings.RABBITMQ_URL
    )

    logger.info("RabbitMQ connection established")

    return connection
