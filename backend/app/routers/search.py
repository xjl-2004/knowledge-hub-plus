from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, require_permissions
from app.schemas.search import SearchDocumentsDto
from app.services import search

router = APIRouter(tags=["search"])
search_permission = [Depends(require_permissions("search"))]


@router.post("/search", dependencies=search_permission)
async def search_documents(dto: SearchDocumentsDto, user: CurrentUser):
    """关键词检索已发布文档。"""
    return await search.search_documents(dto, user)
