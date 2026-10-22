"""分块向量索引（kh_chunk）与混合召回。"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from elasticsearch import NotFoundError

from app.core.config import settings
from app.db import es as es_db
from app.pipeline.types import ChunkHit, DocumentChunk
from app.pipeline.visibility import (
    ES_CHUNK_VISIBILITY_FIELDS,
    es_visibility_filter,
    wrap_es_query,
)

logger = logging.getLogger(__name__)

CHUNK_INDEX = "kh_chunk"

_SOURCE_FIELDS = [
    "chunk_id",
    "document_id",
    "document_title",
    "content",
    "heading",
]

_index_ready = False


async def ensure_index() -> None:
    """索引不存在则创建（含 dense_vector），并补齐可见性字段。"""
    global _index_ready
    if _index_ready:
        return

    client = es_db.get_es()
    if client is None:
        return

    exists = await client.indices.exists(index=CHUNK_INDEX)
    if exists:
        _index_ready = True
    else:
        try:
            await client.indices.create(
                index=CHUNK_INDEX,
                settings={
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "refresh_interval": "5s",
                },
                mappings={
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "document_title": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "search_analyzer": "ik_smart",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "content": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "search_analyzer": "ik_smart",
                        },
                        "heading": {"type": "keyword"},
                        "chunk_index": {"type": "integer"},
                        "total_chunks": {"type": "integer"},
                        "category_id": {"type": "keyword"},
                        "author_id": {"type": "keyword"},
                        "team_id": {"type": "keyword"},
                        "is_public": {"type": "boolean"},
                        "doc_status": {"type": "integer"},
                        "publish_time": {"type": "date"},
                        "indexed_at": {"type": "date"},
                        "embedding": {
                            "type": "dense_vector",
                            "dims": settings.embedding_dimension,
                            "index": True,
                            "similarity": "cosine",
                        },
                    }
                },
            )
            logger.info(
                "ES 索引创建成功：index=%s, dims=%s",
                CHUNK_INDEX,
                settings.embedding_dimension,
            )
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            if "resource_already_exists" in str(exc):
                _index_ready = True
            else:
                logger.error("ES 索引创建失败：%s", exc)
                raise
        _index_ready = True

    try:
        await client.indices.put_mapping(
            index=CHUNK_INDEX,
            properties={
                "is_public": {"type": "boolean"},
                "author_id": {"type": "keyword"},
                "team_id": {"type": "keyword"},
            },
        )
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("%s 可见性 mapping 更新失败：%s", CHUNK_INDEX, exc)


async def delete_by_doc_id(document_id: str) -> None:
    """删除某文档的全部向量块。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过删除向量块（ES 不可用）：documentId=%s", document_id)
        return

    try:
        await client.delete_by_query(
            index=CHUNK_INDEX,
            query={"term": {"document_id": document_id}},
            refresh=True,
        )
        logger.info("已从 ES 删除文档向量块：documentId=%s", document_id)
    except NotFoundError:
        return
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        if "index_not_found" in str(exc):
            return
        logger.error("ES 删除文档块失败：documentId=%s, %s", document_id, exc)


async def index_chunks(chunks: list[DocumentChunk]) -> None:
    """bulk 写入 / 覆盖 chunk（_id = chunkId）。"""
    if not chunks:
        return

    client = es_db.get_es()
    if client is None:
        logger.warning("跳过向量索引写入（ES 不可用）：chunks=%s", len(chunks))
        return

    await ensure_index()

    operations: list[dict[str, Any]] = []
    for chunk in chunks:
        operations.append(
            {"index": {"_index": CHUNK_INDEX, "_id": chunk.chunk_id}}
        )
        operations.append(_build_document(chunk))

    response = await client.bulk(operations=operations, refresh=True)
    if response.get("errors"):
        failed = [
            f"{item.get('index', {}).get('_id')}: "
            f"{item.get('index', {}).get('error', {}).get('reason', 'unknown')}"
            for item in response.get("items", [])
            if item.get("index", {}).get("error")
        ]
        logger.error("ES 批量索引部分失败：%s", ", ".join(failed))
        raise RuntimeError(f"ES 批量索引部分失败：{len(failed)} 条")

    logger.info("ES 批量索引成功：%s chunks → %s", len(chunks), CHUNK_INDEX)


async def update_visibility(document_id: str, visibility: dict[str, Any]) -> None:
    """已发布文档改公开/团队时，批量改块可见性。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过向量可见性更新（ES 不可用）：documentId=%s", document_id)
        return

    try:
        result = await client.update_by_query(
            index=CHUNK_INDEX,
            refresh=True,
            query={"term": {"document_id": document_id}},
            script={
                "source": (
                    "ctx._source.is_public = params.is_public; "
                    "ctx._source.team_id = params.team_id; "
                    "ctx._source.author_id = params.author_id;"
                ),
                "params": {
                    "is_public": visibility.get("isPublic"),
                    "team_id": visibility.get("teamId"),
                    "author_id": visibility.get("authorId"),
                },
            },
        )
        logger.info(
            "向量块可见性已更新：documentId=%s, updated=%s",
            document_id,
            result.get("updated", 0),
        )
    except NotFoundError:
        return
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("向量块可见性更新失败：documentId=%s, %s", document_id, exc)


def _clamp_top_k(top_k: int) -> int:
    return min(max(top_k, 1), 50)


def _map_hits(hits: list[Any]) -> list[ChunkHit]:
    result: list[ChunkHit] = []
    for hit in hits:
        source = hit.get("_source") or {}
        result.append(
            ChunkHit(
                chunk_id=str(source.get("chunk_id") or hit.get("_id")),
                document_id=str(source.get("document_id") or ""),
                document_title=str(source.get("document_title") or ""),
                content=str(source.get("content") or ""),
                heading=source.get("heading"),
                score=hit.get("_score") or 0,
            )
        )
    return result


async def keyword_search(
    query: str, top_k: int = 20, scope: Any = None
) -> list[ChunkHit]:
    """BM25 关键词检索（标题 + 正文）。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过关键词检索（ES 不可用）")
        return []

    trimmed = query.strip()
    if not trimmed:
        return []

    k = _clamp_top_k(top_k)
    visibility = es_visibility_filter(scope, ES_CHUNK_VISIBILITY_FIELDS)
    try:
        response = await client.search(
            index=CHUNK_INDEX,
            size=k,
            query=wrap_es_query(
                {
                    "multi_match": {
                        "query": trimmed,
                        "fields": ["document_title^2", "content"],
                        "analyzer": "ik_smart",
                    }
                },
                visibility,
            ),
            source=_SOURCE_FIELDS,
        )
        return _map_hits(response["hits"]["hits"])
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("关键词检索失败：%s", exc)
        return []


async def knn_search(
    query_vector: list[float], top_k: int = 20, scope: Any = None
) -> list[ChunkHit]:
    """kNN 向量检索（cosine）。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过向量检索（ES 不可用）")
        return []
    if not query_vector:
        return []

    k = _clamp_top_k(top_k)
    visibility = es_visibility_filter(scope, ES_CHUNK_VISIBILITY_FIELDS)
    knn: dict[str, Any] = {
        "field": "embedding",
        "query_vector": query_vector,
        "k": k,
        "num_candidates": max(k * 10, 50),
    }
    if visibility:
        knn["filter"] = visibility

    try:
        response = await client.search(
            index=CHUNK_INDEX,
            size=k,
            knn=knn,
            source=_SOURCE_FIELDS,
        )
        return _map_hits(response["hits"]["hits"])
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("向量检索失败：%s", exc)
        return []


def rrf_fuse(
    keyword_hits: list[ChunkHit],
    vector_hits: list[ChunkHit],
    rrf_c: int = 60,
) -> list[ChunkHit]:
    """Reciprocal Rank Fusion：score = Σ 1 / (C + rank)。"""
    fused: dict[str, ChunkHit] = {}

    def add_channel(hits: list[ChunkHit], channel: str) -> None:
        for rank, hit in enumerate(sorted(hits, key=lambda item: item.score, reverse=True)):
            rrf = 1 / (rrf_c + rank + 1)
            existing = fused.get(hit.chunk_id)
            if existing is None:
                fused[hit.chunk_id] = ChunkHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    document_title=hit.document_title,
                    content=hit.content,
                    heading=hit.heading,
                    score=rrf,
                    bm25_score=hit.score if channel == "keyword" else 0.0,
                    vector_score=hit.score if channel == "vector" else 0.0,
                )
                continue
            existing.score += rrf
            if channel == "keyword":
                existing.bm25_score = hit.score
            else:
                existing.vector_score = hit.score

    add_channel(keyword_hits, "keyword")
    add_channel(vector_hits, "vector")
    return sorted(fused.values(), key=lambda item: item.score, reverse=True)


async def search_hybrid(
    query: str,
    query_vector: list[float] | None = None,
    hybrid_top_k: int = 20,
    rrf_c: int = 60,
    scope: Any = None,
) -> list[ChunkHit]:
    """关键词 + 向量并行召回，再按 chunkId 做 RRF 融合。"""
    top_k = _clamp_top_k(hybrid_top_k)
    effective_c = rrf_c if rrf_c > 0 else 60

    if query_vector:
        keyword_hits, vector_hits = await asyncio.gather(
            keyword_search(query, top_k, scope),
            knn_search(query_vector, top_k, scope),
        )
    else:
        keyword_hits = await keyword_search(query, top_k, scope)
        vector_hits = []

    fused = rrf_fuse(keyword_hits, vector_hits, effective_c)
    logger.info(
        "混合检索 RRF：keyword=%s, vector=%s, fused=%s",
        len(keyword_hits),
        len(vector_hits),
        len(fused),
    )
    return fused


def _build_document(chunk: DocumentChunk) -> dict[str, Any]:
    document: dict[str, Any] = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_title": chunk.document_title,
        "content": chunk.content,
        "heading": chunk.heading,
        "chunk_index": chunk.chunk_index,
        "total_chunks": chunk.total_chunks,
        "category_id": chunk.category_id,
        "author_id": chunk.author_id,
        "team_id": chunk.team_id,
        "is_public": chunk.is_public,
        "doc_status": chunk.doc_status,
        "publish_time": chunk.publish_time,
        "indexed_at": datetime.now().isoformat(),
    }
    if chunk.embedding:
        document["embedding"] = chunk.embedding
    return document
