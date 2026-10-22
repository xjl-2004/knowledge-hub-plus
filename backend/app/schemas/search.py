from pydantic import Field

from app.schemas.base import CamelModel


class SearchDocumentsDto(CamelModel):
    """全文搜索请求。"""

    keyword: str = Field(..., min_length=1)
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=50)
    category_id: str | None = None
    author_id: str | None = None
