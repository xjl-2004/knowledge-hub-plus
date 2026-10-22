"""文本向量化（DashScope OpenAI 兼容端点）。"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# DashScope text-embedding-v3 单次最多 10 条
MAX_BATCH_SIZE = 10


class EmbeddingUnavailable(RuntimeError):
    """未配置 Embedding Key。"""


def _endpoint() -> str:
    return f"{settings.embedding_base_url.rstrip('/')}/embeddings"


def _batch_size() -> int:
    configured = settings.embedding_batch_size or MAX_BATCH_SIZE
    return max(1, min(configured, MAX_BATCH_SIZE))


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化，内部按批次大小切片。"""
    if not texts:
        return []

    api_key = settings.embedding_key
    if not api_key:
        raise EmbeddingUnavailable(
            "未配置 EMBEDDING_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY"
        )

    vectors: list[list[float]] = []
    batch_size = _batch_size()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            payload: dict = {
                "model": settings.embedding_model,
                "input": batch,
            }
            if settings.embedding_dimension:
                payload["dimensions"] = settings.embedding_dimension

            response = await client.post(_endpoint(), headers=headers, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Embedding 调用失败：status={response.status_code}, "
                    f"{response.text[:200]}"
                )

            data = response.json().get("data") or []
            vectors.extend(item.get("embedding") or [] for item in data)

    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding 数量不匹配：expect={len(texts)}, got={len(vectors)}"
        )

    logger.debug("嵌入完成：count=%s", len(vectors))
    return vectors


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]
