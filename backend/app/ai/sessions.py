"""AI 会话与消息持久化。"""

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import long_memory, short_memory
from app.core.errors import not_found
from app.core.snowflake import next_id
from app.models import AiMessage, AiSession

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "新对话"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_session(row: AiSession) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "userId": str(row.user_id),
        "title": row.title,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def serialize_message(row: AiMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "sessionId": str(row.session_id),
        "role": row.role,
        "content": row.content,
        "sources": row.sources,
        "createdAt": _iso(row.created_at),
    }


def title_from_question(question: str) -> str:
    text = re.sub(r"\s+", " ", question or "").strip()
    if not text:
        return DEFAULT_TITLE
    return f"{text[:30]}…" if len(text) > 30 else text


async def _get_owned(db: AsyncSession, user_id: str, session_id: str) -> AiSession:
    result = await db.execute(
        select(AiSession).where(
            AiSession.id == int(session_id), AiSession.user_id == int(user_id)
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise not_found("会话不存在")
    return row


async def page_mine(
    db: AsyncSession, user_id: str, page: int, page_size: int
) -> dict[str, Any]:
    total = (
        await db.execute(
            select(func.count())
            .select_from(AiSession)
            .where(AiSession.user_id == int(user_id))
        )
    ).scalar_one()
    result = await db.execute(
        select(AiSession)
        .where(AiSession.user_id == int(user_id))
        .order_by(AiSession.updated_at.desc(), AiSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_session(row) for row in result.scalars().all()]
    return {"items": items, "total": int(total), "page": page, "pageSize": page_size}


async def create(
    db: AsyncSession, user_id: str, title: str | None = None
) -> dict[str, Any]:
    now = datetime.now()
    row = AiSession(
        id=next_id(),
        user_id=int(user_id),
        title=((title or "").strip() or DEFAULT_TITLE)[:80],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    return serialize_session(row)


async def rename(
    db: AsyncSession, user_id: str, session_id: str, title: str
) -> dict[str, Any]:
    row = await _get_owned(db, user_id, session_id)
    row.title = title.strip()[:80]
    row.updated_at = datetime.now()
    await db.commit()
    return serialize_session(row)


async def touch_title(
    db: AsyncSession, user_id: str, session_id: str, question: str
) -> dict[str, Any]:
    """仍为默认标题时，用首问覆盖。"""
    row = await _get_owned(db, user_id, session_id)
    if row.title == DEFAULT_TITLE:
        row.title = title_from_question(question)
        row.updated_at = datetime.now()
        await db.commit()
    return serialize_session(row)


async def remove(db: AsyncSession, user_id: str, session_id: str) -> dict[str, str]:
    await _get_owned(db, user_id, session_id)
    await db.execute(delete(AiMessage).where(AiMessage.session_id == int(session_id)))
    await db.execute(delete(AiSession).where(AiSession.id == int(session_id)))
    await db.commit()
    await short_memory.clear(user_id, session_id)
    await long_memory.clear_session(user_id, session_id)
    return {"message": "已删除"}


async def list_messages(
    db: AsyncSession, user_id: str, session_id: str
) -> list[dict[str, Any]]:
    await _get_owned(db, user_id, session_id)
    result = await db.execute(
        select(AiMessage)
        .where(AiMessage.session_id == int(session_id))
        .order_by(AiMessage.created_at.asc(), AiMessage.id.asc())
    )
    return [serialize_message(row) for row in result.scalars().all()]


async def list_recent_messages(
    db: AsyncSession, user_id: str, session_id: str, limit: int
) -> list[dict[str, str]]:
    """最近 N 条，时间正序，供 Redis miss 时回填工作窗口。"""
    await _get_owned(db, user_id, session_id)
    result = await db.execute(
        select(AiMessage)
        .where(AiMessage.session_id == int(session_id))
        .order_by(AiMessage.created_at.desc(), AiMessage.id.desc())
        .limit(max(limit, 1))
    )
    rows = list(reversed(result.scalars().all()))
    return [
        {"role": row.role, "content": row.content}
        for row in rows
        if row.content and row.content.strip()
    ]


async def append_turn(
    db: AsyncSession,
    user_id: str,
    session_id: str | None,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """问答落库：无 sessionId 则新建；标题在仍为默认名时用首问覆盖。"""
    if session_id:
        row = await _get_owned(db, user_id, session_id)
    else:
        now = datetime.now()
        row = AiSession(
            id=next_id(),
            user_id=int(user_id),
            title=title_from_question(question),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()

    if row.title == DEFAULT_TITLE:
        row.title = title_from_question(question)
    row.updated_at = datetime.now()

    now = datetime.now()
    db.add(
        AiMessage(
            id=next_id(),
            session_id=row.id,
            role="user",
            content=question,
            sources=None,
            created_at=now,
        )
    )
    db.add(
        AiMessage(
            id=next_id(),
            session_id=row.id,
            role="assistant",
            content=answer,
            sources=sources or None,
            created_at=now,
        )
    )
    await db.commit()
    return serialize_session(row)
