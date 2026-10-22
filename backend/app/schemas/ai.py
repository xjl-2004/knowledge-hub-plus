"""AI 对话相关 DTO。"""

from typing import Annotated, Any, Optional

from pydantic import Field

from app.schemas.base import CamelModel


class ChatDto(CamelModel):
    """RAG 对话请求。"""

    session_id: Annotated[Optional[str], Field(None, description="已有会话 ID，不传则新建")]
    content: Annotated[str, Field(min_length=1, description="用户问题")]
    top_k: Annotated[Optional[int], Field(
        5, ge=1, le=10, description="召回块数，默认 5"
    )]


class ChatStreamDto(CamelModel):
    """AI SDK UI Message Stream 请求体。"""

    messages: list[dict] = Field(..., description="对话消息历史")
    session_id: Annotated[Optional[str], Field(None, description="已有会话 ID")]
    top_k: Annotated[Optional[int], Field(
        5, ge=1, le=10, description="召回块数，默认 5"
    )]
    id: Annotated[Optional[str], Field(None)]
    trigger: Annotated[Any, Field(None)]
    message_id: Annotated[Any, Field(None)]


class QuerySessionDto(CamelModel):
    """会话列表分页请求。"""

    page: Annotated[int, Field(1, ge=1)]
    page_size: Annotated[int, Field(20, ge=1, le=100)]


class CreateSessionDto(CamelModel):
    """新建会话请求。"""

    title: Annotated[Optional[str], Field(None, max_length=80, description="会话标题")]


class UpdateSessionDto(CamelModel):
    """重命名会话请求。"""

    title: Annotated[str, Field(min_length=1, max_length=80, description="新标题")]
