"""文档级全文检索索引（kh_document）。"""

import logging
from datetime import datetime
from typing import Any

from elasticsearch import NotFoundError

from app.db import es as es_db
from app.pipeline.visibility import (
    ES_DOC_VISIBILITY_FIELDS,
    es_visibility_filter,
)
from app.schemas.base import page_result

logger = logging.getLogger(__name__)

ES_INDEX = "kh_document"

_ik_text = {
    "type": "text",
    "analyzer": "ik_max_word",
    "search_analyzer": "ik_smart",
}

_index_ready = False


async def ensure_index() -> None:
    """索引不存在则创建，并补齐可见性字段。"""
    global _index_ready
    if _index_ready:
        return

    client = es_db.get_es()
    if client is None:
        return

    exists = await client.indices.exists(index=ES_INDEX)
    if not exists:
        await client.indices.create(
            index=ES_INDEX,
            mappings={
                "properties": {
                    "id": {"type": "keyword"},
                    "title": _ik_text,
                    "summary": _ik_text,
                    "content": _ik_text,
                    "tags": {"type": "keyword"},
                    "status": {"type": "integer"},
                    "categoryId": {"type": "keyword"},
                    "authorId": {"type": "keyword"},
                    "teamId": {"type": "keyword"},
                    "isPublic": {"type": "boolean"},
                    "publishTime": {"type": "date"},
                }
            },
        )
        logger.info("已创建 ES 索引：%s", ES_INDEX)

    try:
        await client.indices.put_mapping(
            index=ES_INDEX,
            properties={
                "isPublic": {"type": "boolean"},
                "teamId": {"type": "keyword"},
                "authorId": {"type": "keyword"},
            },
        )
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("%s 可见性 mapping 更新失败：%s", ES_INDEX, exc)

    _index_ready = True


async def index_document(doc: dict[str, Any]) -> None:
    """写入 / 覆盖一篇文档的检索记录。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过搜索索引写入（ES 不可用）：documentId=%s", doc.get("id"))
        return

    document_id = str(doc.get("id"))
    await ensure_index()
    payload = {**doc, "indexedAt": datetime.now().isoformat()}
    await client.index(index=ES_INDEX, id=document_id, document=payload, refresh=True)
    logger.info("搜索索引已写入 ES：documentId=%s", document_id)


async def update_visibility(
    document_id: str,
    visibility: dict[str, Any],
) -> None:
    """只改可见性字段，不重写全文。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过搜索可见性更新（ES 不可用）：documentId=%s", document_id)
        return

    try:
        await client.update(
            index=ES_INDEX,
            id=document_id,
            doc={
                "isPublic": visibility.get("isPublic"),
                "teamId": visibility.get("teamId"),
                "authorId": visibility.get("authorId"),
            },
            refresh=True,
        )
        logger.info("搜索索引可见性已更新：documentId=%s", document_id)
    except NotFoundError:
        logger.warning("搜索索引记录不存在：documentId=%s", document_id)
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("搜索索引可见性更新失败：documentId=%s, %s", document_id, exc)


async def delete_document(document_id: str) -> None:
    """下架 / 删除时移除检索记录。"""
    client = es_db.get_es()
    if client is None:
        logger.warning("跳过搜索索引删除（ES 不可用）：documentId=%s", document_id)
        return

    try:
        await client.delete(index=ES_INDEX, id=document_id, refresh=True)
    except NotFoundError:
        pass
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("ES 删除失败：documentId=%s, %s", document_id, exc)
        return

    logger.info("搜索索引已删除：documentId=%s", document_id)


async def search_documents(
    keyword: str,
    page: int = 1,
    page_size: int = 10,
    category_id: str | None = None,
    author_id: str | None = None,
    scope: Any = None,
) -> dict[str, Any]:
    """关键词检索；ES 不可用时返回空分页而不抛错。"""
    page = page or 1
    page_size = min(page_size or 10, 50)

    client = es_db.get_es()
    if client is None:
        logger.warning("跳过搜索查询（ES 不可用）")
        return page_result([], 0, page, page_size)

    filters: list[dict[str, Any]] = []
    visibility = es_visibility_filter(scope, ES_DOC_VISIBILITY_FIELDS)
    if visibility:
        filters.append(visibility)
    if category_id:
        filters.append({"term": {"categoryId": category_id}})
    if author_id:
        filters.append({"term": {"authorId": author_id}})

    multi_match = {
        "multi_match": {
            "query": keyword.strip(),
            "fields": ["title^3", "summary^2", "content"],
            "analyzer": "ik_smart",
        }
    }
    query: dict[str, Any] = (
        {"bool": {"must": [multi_match], "filter": filters}}
        if filters
        else multi_match
    )

    try:
        response = await client.search(
            index=ES_INDEX,
            from_=(page - 1) * page_size,
            size=page_size,
            query=query,
            source_excludes=["content"],
            highlight={
                "fields": {
                    "title": {"number_of_fragments": 0},
                    "content": {"fragment_size": 160, "number_of_fragments": 3},
                    "summary": {"fragment_size": 120, "number_of_fragments": 1},
                }
            },
        )
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("搜索查询失败：%s", exc)
        return page_result([], 0, page, page_size)

    total_raw = response["hits"]["total"]
    total = total_raw if isinstance(total_raw, int) else total_raw.get("value", 0)

    items: list[dict[str, Any]] = []
    for hit in response["hits"]["hits"]:
        source = hit.get("_source") or {}
        highlight = hit.get("highlight") or {}
        items.append(
            {
                "id": str(source.get("id") or hit.get("_id")),
                "title": source.get("title") or "",
                "summary": source.get("summary"),
                "categoryId": source.get("categoryId"),
                "tags": source.get("tags"),
                "authorId": source.get("authorId"),
                "teamId": source.get("teamId"),
                "isPublic": source.get("isPublic"),
                "status": source.get("status"),
                "publishTime": source.get("publishTime"),
                "score": hit.get("_score") or 0,
                "highlight": {
                    "title": highlight.get("title") or [],
                    "summary": highlight.get("summary") or [],
                    "content": highlight.get("content") or [],
                },
            }
        )

    return page_result(items, total, page, page_size)
