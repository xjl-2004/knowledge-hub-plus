from pydantic import Field

from app.schemas.base import CamelModel


class CreateDocumentDto(CamelModel):
    title: str
    content: str
    summary: str | None = None
    category_id: str | None = None
    team_id: str | None = None
    cover_image: str | None = None
    tags: str | None = None
    status: int | None = Field(None, ge=0, le=3)
    remark: str | None = None
    is_public: bool | None = None


class UpdateDocumentDto(CamelModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    category_id: str | None = None
    team_id: str | None = None
    cover_image: str | None = None
    tags: str | None = None
    status: int | None = Field(None, ge=0, le=3)
    remark: str | None = None
    is_public: bool | None = None


class UploadParseDto(CamelModel):
    category_id: str | None = None
    team_id: str | None = None
    tags: str | None = None
    remark: str | None = None
    is_public: bool | None = None


class ReviewDecisionDto(CamelModel):
    review_comment: str | None = None
