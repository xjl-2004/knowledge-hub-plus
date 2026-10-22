from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, require_permissions
from app.schemas.retrieval import RagSearchDto
from app.services import retrieval

router = APIRouter(tags=["ai"])
search_permission = [Depends(require_permissions("search"))]


@router.post("/rag/search", dependencies=search_permission)
async def rag_search(dto: RagSearchDto, user: CurrentUser):
    """RAG 混合检索：关键词 BM25 + 向量 kNN → RRF。"""
    return await retrieval.retrieve(dto.query.strip(), dto.top_k, user)
