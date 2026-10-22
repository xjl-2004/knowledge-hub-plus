from pydantic import Field

from app.schemas.base import CamelModel


class RagSearchDto(CamelModel):
    """RAG 混合检索请求（不生成回答）。"""

    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)
