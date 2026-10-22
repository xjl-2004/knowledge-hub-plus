import logging

import aio_pika

from app.core.config import settings

logger = logging.getLogger(__name__)

_connection: aio_pika.abc.AbstractRobustConnection | None = None


async def get_connection() -> aio_pika.abc.AbstractRobustConnection | None:
    global _connection
    if not settings.rabbitmq_enabled:
        return None
    if _connection is None or _connection.is_closed:
        try:
            _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            logger.warning("RabbitMQ 连接失败：%s", exc)
            return None
    return _connection


async def ping() -> bool:
    connection = await get_connection()
    if connection is None:
        return False
    channel = await connection.channel()
    await channel.close()
    return True


async def close() -> None:
    global _connection
    if _connection is not None and not _connection.is_closed:
        await _connection.close()
    _connection = None
