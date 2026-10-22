"""文本重排（DashScope text-rerank）。"""

import logging

import httpx

from app.core.config import settings
from app.pipeline.types import ChunkHit

logger = logging.getLogger(__name__)

MAX_DOCUMENT_LENGTH = 2000


def is_enabled() -> bool:
    return settings.rag_rerank_enabled and bool(settings.rerank_key)


def _endpoint() -> str:
    base = settings.rerank_base_url.rstrip("/")
    return f"{base}/api/v1/services/rerank/text-rerank/text-rerank"


def _to_document(hit: ChunkHit) -> str:
    heading = f"{hit.heading}\n" if hit.heading else ""
    text = f"{hit.document_title}\n{heading}{hit.content}".strip()
    if len(text) > MAX_DOCUMENT_LENGTH:
        return f"{text[:MAX_DOCUMENT_LENGTH]}..."
    return text


async def rerank(
    query: str, candidates: list[ChunkHit], top_n: int
) -> list[ChunkHit] | None:
    """按 query 与候选块的相关性重排；未启用或失败返回 None。"""
    if not candidates:
        return []

    if not is_enabled():
        logger.warning("Reranker 未启用或未配置 Key，跳过重排")
        return None

    payload = {
        "model": settings.rag_rerank_model,
        "input": {
            "query": query,
            "documents": [_to_document(item) for item in candidates],
        },
        "parameters": {
            "return_documents": False,
            "top_n": min(top_n, len(candidates)),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                _endpoint(),
                headers={
                    "Authorization": f"Bearer {settings.rerank_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        body = response.json()
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("Rerank 异常，降级为 RRF：%s", exc)
        return None

    if response.status_code >= 400:
        logger.warning(
            "Rerank 调用失败：status=%s, code=%s, message=%s",
            response.status_code,
            body.get("code", ""),
            body.get("message", ""),
        )
        return None

    results = (body.get("output") or {}).get("results") or body.get("results") or []
    if not results:
        logger.warning("Rerank 返回空结果，降级为 RRF")
        return None

    reranked: list[ChunkHit] = []
    for item in results:
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(candidates):
            continue
        source = candidates[index]
        reranked.append(
            ChunkHit(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                document_title=source.document_title,
                content=source.content,
                heading=source.heading,
                score=item.get("relevance_score", 0),
                bm25_score=source.bm25_score,
                vector_score=source.vector_score,
            )
        )

    logger.info(
        "Rerank 完成：model=%s, in=%s, out=%s",
        settings.rag_rerank_model,
        len(candidates),
        len(reranked),
    )
    return reranked
