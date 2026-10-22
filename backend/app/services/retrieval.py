"""kh_chunk 混合检索。"""

import logging
from typing import Any

from app.core.config import settings
from app.core.deps import AuthUser
from app.integrations import rerank
from app.pipeline import embedding, vector_index
from app.services.documents import DocumentAccessScope, access_from_user

logger = logging.getLogger(__name__)


async def retrieve(
    query: str, top_k: int = 5, user: AuthUser | None = None
) -> list[dict[str, Any]]:
    """查询向量化后走关键词 + 向量双路召回，按 RRF 分数截断。"""
    query_vector = await _embed_query(query)
    scope = (
        access_from_user(user)
        if user
        else DocumentAccessScope(unrestricted=False, user_id="", team_ids=[])
    )

    fused = await vector_index.search_hybrid(
        query=query,
        query_vector=query_vector,
        hybrid_top_k=settings.rag_hybrid_top_k,
        rrf_c=settings.rag_rrf_c,
        scope=scope,
    )
    if not fused:
        logger.info("混合检索无结果：queryLength=%s", len(query))
        return []

    reranked = await rerank.rerank(query, fused, len(fused))
    if reranked:
        min_score = settings.rag_min_score
        kept = (
            [hit for hit in reranked if hit.score >= min_score]
            if min_score > 0
            else reranked
        )
        top = kept[:top_k]
        logger.info(
            "检索过滤：rerank=%s, minScore=%s, kept=%s, return=%s",
            len(reranked),
            min_score,
            len(kept),
            len(top),
        )
        return [hit.to_dict() for hit in top]

    return [hit.to_dict() for hit in fused[:top_k]]


async def _embed_query(query: str) -> list[float] | None:
    try:
        return await embedding.embed_text(query)
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("查询向量化失败，仅走关键词：%s", exc)
        return None
