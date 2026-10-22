import json
import logging
from typing import Any, Awaitable, Callable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustChannel

from app.core.config import settings
from app.db import amqp
from app.mq.constants import TOPOLOGY

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]

_handlers: dict[str, MessageHandler] = {}
_channel: AbstractRobustChannel | None = None


def register_handler(queue: str, handler: MessageHandler) -> None:
    _handlers[queue] = handler


async def initialize() -> None:
    global _channel
    if not settings.rabbitmq_enabled:
        logger.warning("RabbitMQ 已禁用（RABBITMQ_ENABLED=false）")
        return
    if _channel is not None and not _channel.is_closed:
        return

    connection = await amqp.get_connection()
    if connection is None:
        logger.warning("RabbitMQ 不可用，消息队列功能暂停")
        return

    _channel = await connection.channel()
    await _channel.set_qos(prefetch_count=10)
    await _declare_topology(_channel)
    await _bind_consumers(_channel)
    logger.info("RabbitMQ 拓扑已声明（RAG + Search + KG）")


async def _declare_topology(channel: AbstractRobustChannel) -> None:
    for exchange_name, queue_name, routing_keys in TOPOLOGY:
        exchange = await channel.declare_exchange(
            exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(queue_name, durable=True)
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)


def _build_callback(queue_name: str, handler: MessageHandler):
    async def on_message(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=False):
            payload = json.loads(message.body.decode("utf-8"))
            await handler(payload)

    async def safe_on_message(message: AbstractIncomingMessage) -> None:
        try:
            await on_message(message)
        except Exception as exc:
            logger.error("消费失败 queue=%s: %s", queue_name, exc)

    return safe_on_message


async def _bind_consumers(channel: AbstractRobustChannel) -> None:
    for queue_name, handler in _handlers.items():
        queue = await channel.declare_queue(queue_name, durable=True)
        await queue.consume(_build_callback(queue_name, handler))
        logger.info("已注册消费者：%s", queue_name)


async def publish(
    exchange: str, routing_key: str, payload: dict[str, Any]
) -> bool:
    if not settings.rabbitmq_enabled:
        logger.warning(
            "跳过发消息（MQ 已禁用）：exchange=%s, rk=%s", exchange, routing_key
        )
        return False
    if _channel is None or _channel.is_closed:
        logger.warning(
            "跳过发消息（MQ 不可用）：exchange=%s, rk=%s", exchange, routing_key
        )
        return False

    try:
        target = await _channel.get_exchange(exchange)
        await target.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
        return True
    except Exception as exc:
        logger.warning(
            "发消息失败：exchange=%s, rk=%s, error=%s", exchange, routing_key, exc
        )
        return False


async def close() -> None:
    global _channel
    if _channel is not None and not _channel.is_closed:
        await _channel.close()
    _channel = None
