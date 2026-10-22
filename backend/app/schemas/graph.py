from pydantic import Field

from app.schemas.base import CamelModel


class GraphQueryDto(CamelModel):
    type: str | None = None
    limit: int = Field(200, ge=1, le=1000)


class GraphSearchDto(CamelModel):
    keyword: str = Field(..., min_length=1)
    limit: int = Field(50, ge=1, le=200)


class GraphOverviewDto(CamelModel):
    keyword: str | None = None
    entity_type: str | None = None
    from_date: str | None = Field(None, alias="from")
    to_date: str | None = Field(None, alias="to")
    doc_limit: int = Field(24, ge=1, le=80)
