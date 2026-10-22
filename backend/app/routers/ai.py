from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.ai import chat as chat_service
from app.ai import sessions as session_service
from app.ai import stream as stream_service
from app.core.deps import CurrentUser, DbSession, require_permissions
from app.schemas.ai import (
    ChatDto,
    ChatStreamDto,
    CreateSessionDto,
    QuerySessionDto,
    UpdateSessionDto,
)
from app.schemas.retrieval import RagSearchDto
from app.services import retrieval

router = APIRouter(tags=["ai"])
search_permission = [Depends(require_permissions("search"))]

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
}


@router.post("/rag/search", dependencies=search_permission)
async def rag_search(dto: RagSearchDto, user: CurrentUser):
    """RAG 混合检索：关键词 BM25 + 向量 kNN → RRF。"""
    return await retrieval.retrieve(dto.query.strip(), dto.top_k, user)


@router.post("/ai/chat", dependencies=search_permission)
async def chat(dto: ChatDto, user: CurrentUser, db: DbSession):
    """Agentic RAG 对话：评估切题，不足则改写再查。"""
    return await chat_service.chat(
        db, dto.content, dto.top_k or 5, user, dto.session_id
    )


@router.post("/ai/chat/stream", dependencies=search_permission)
async def stream_chat(dto: ChatStreamDto, user: CurrentUser):
    """Agentic RAG 流式作答，输出 AI SDK UI Message Stream。"""
    return StreamingResponse(
        stream_service.stream_chat(dto, user),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@router.get("/ai/sessions", dependencies=search_permission)
async def list_sessions(
    user: CurrentUser,
    query: Annotated[QuerySessionDto, Depends()],
    db: DbSession,
):
    """我的会话分页。"""
    return await session_service.page_mine(
        db, user.user_id, query.page, query.page_size
    )


@router.post("/ai/sessions", dependencies=search_permission)
async def create_session(dto: CreateSessionDto, user: CurrentUser, db: DbSession):
    """新建空会话。"""
    return await session_service.create(db, user.user_id, dto.title)


@router.get("/ai/sessions/{session_id}/messages", dependencies=search_permission)
async def list_messages(session_id: str, user: CurrentUser, db: DbSession):
    """会话消息列表。"""
    return await session_service.list_messages(db, user.user_id, session_id)


@router.patch("/ai/sessions/{session_id}", dependencies=search_permission)
async def rename_session(
    session_id: str, dto: UpdateSessionDto, user: CurrentUser, db: DbSession
):
    """重命名会话。"""
    return await session_service.rename(db, user.user_id, session_id, dto.title)


@router.delete("/ai/sessions/{session_id}", dependencies=search_permission)
async def remove_session(session_id: str, user: CurrentUser, db: DbSession):
    """删除会话及消息。"""
    return await session_service.remove(db, user.user_id, session_id)
