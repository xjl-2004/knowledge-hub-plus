"""对话短期记忆：Redis 热窗口。"""

import json
import logging

from app.core.config import settings
from app.db.redis import get_redis

logger = logging.getLogger(__name__)

Message = dict[str, str]


def _key(user_id: str, session_id: str) -> str:
    return (
        f"{settings.chat_short_memory_key_prefix}:{user_id}:"
        f"{session_id}:messages"
    )


def _clean(messages: list[Message]) -> list[Message]:
    result: list[Message] = []
    for message in messages:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            result.append({"role": role, "content": content})
    return result


async def try_load(user_id: str, session_id: str) -> list[Message] | None:
    """命中返回消息；key 不存在或 Redis 故障返回 None。"""
    try:
        raw = await get_redis().get(_key(user_id, session_id))
        if not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return None
        return _clean(parsed)
    except Exception as exc:  # pragma: no cover - Redis 不可用
        logger.warning("短期记忆 Redis 读取失败，改走数据库：%s", exc)
        return None


async def save(user_id: str, session_id: str, messages: list[Message]) -> None:
    working = _clean(messages)[-settings.chat_short_memory_max_messages :]
    try:
        await get_redis().set(
            _key(user_id, session_id),
            json.dumps(working, ensure_ascii=False),
            ex=settings.chat_short_memory_ttl_seconds,
        )
    except Exception as exc:  # pragma: no cover - Redis 不可用
        logger.warning("短期记忆 Redis 写入失败：%s", exc)


async def append_turn(
    user_id: str,
    session_id: str,
    history: list[Message],
    question: str,
    answer: str,
) -> None:
    await save(
        user_id,
        session_id,
        list(history)
        + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
    )


async def clear(user_id: str, session_id: str) -> None:
    try:
        await get_redis().delete(_key(user_id, session_id))
    except Exception as exc:  # pragma: no cover - Redis 不可用
        logger.warning("短期记忆 Redis 删除失败：%s", exc)


def window_size() -> int:
    return settings.chat_short_memory_max_messages
