"""发布后知识管线编排：加载文档 → 调用索引服务。"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from sqlalchemy import select

from app.db import mongo as mongo_db
from app.db.session import SessionLocal
from app.models import Document
from app.pipeline import chunking, embedding, graph_build, search_index, vector_index
from app.pipeline.types import PipelineDocument

logger = logging.getLogger(__name__)

# 与文档状态机保持一致：1 = 已发布
PUBLISHED_STATUS = 1


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _to_pipeline_document(doc: Document, content: str) -> PipelineDocument:
    return PipelineDocument(
        id=str(doc.id),
        title=doc.title,
        content=content,
        summary=doc.summary,
        category_id=str(doc.category_id) if doc.category_id else None,
        author_id=str(doc.author_id) if doc.author_id else None,
        team_id=str(doc.team_id) if doc.team_id else None,
        status=doc.status,
        tags=doc.tags,
        is_public=bool(doc.is_public),
        view_count=doc.view_count or 0,
        like_count=doc.like_count or 0,
        comment_count=doc.comment_count or 0,
        publish_time=_iso(doc.publish_time),
        created_at=_iso(doc.created_at),
        updated_at=_iso(doc.updated_at),
    )


async def _fetch_content(content_id: str) -> str:
    try:
        object_id = ObjectId(content_id)
    except Exception:
        return ""
    record = await mongo_db.document_content_collection().find_one(
        {"_id": object_id, "deleted": False}
    )
    return (record or {}).get("content") or ""


async def _load_documents(document_ids: list[str]) -> list[PipelineDocument]:
    """按 ID 列表加载元数据 + Mongo 正文，保持入参顺序。"""
    numeric_ids = []
    for document_id in document_ids:
        try:
            numeric_ids.append(int(document_id))
        except (TypeError, ValueError):
            continue

    if not numeric_ids:
        return []

    async with SessionLocal() as db:
        result = await db.execute(
            select(Document).where(
                Document.id.in_(numeric_ids), Document.deleted.is_(False)
            )
        )
        rows = result.scalars().all()

    by_id = {str(row.id): row for row in rows}
    documents: list[PipelineDocument] = []
    for document_id in document_ids:
        row = by_id.get(str(document_id))
        if row is None:
            continue
        content = await _fetch_content(row.content_id)
        documents.append(_to_pipeline_document(row, content))
    return documents


async def _load_all_published() -> list[PipelineDocument]:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Document).where(
                Document.deleted.is_(False), Document.status == PUBLISHED_STATUS
            )
        )
        rows = result.scalars().all()

    documents: list[PipelineDocument] = []
    for row in rows:
        content = await _fetch_content(row.content_id)
        documents.append(_to_pipeline_document(row, content))
    return documents


async def handle_rag_reindex(
    action: str | None, document_ids: list[str] | None = None
) -> None:
    """RAG 重建 / 删除：清旧块 → 分块 → 嵌入 → 写入 kh_chunk。"""
    if action == "DELETE_BY_DOC_IDS" and document_ids:
        for document_id in document_ids:
            await vector_index.delete_by_doc_id(document_id)
        return

    if action != "BY_DOC_IDS" or not document_ids:
        logger.warning("忽略未支持的 RAG 消息：type=%s", action)
        return

    documents = await _load_documents(document_ids)
    logger.info("RAG 开始索引：type=%s, total=%s", action, len(documents))

    for document in documents:
        try:
            await _reindex_one(document)
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            logger.error(
                "RAG 索引失败：documentId=%s, %s", document.id, exc
            )


async def _reindex_one(document: PipelineDocument) -> None:
    if not document.content.strip():
        logger.warning("文档内容为空，跳过 RAG：documentId=%s", document.id)
        return

    # 先清旧块，避免重复发布时残留
    await vector_index.delete_by_doc_id(document.id)

    chunks = await chunking.chunk(
        document.content,
        document.id,
        document.title,
        category_id=document.category_id,
        author_id=document.author_id,
        team_id=document.team_id,
        is_public=document.is_public,
        doc_status=document.status,
        publish_time=document.publish_time,
    )
    if not chunks:
        return

    vectors = await embedding.embed_texts([item.content for item in chunks])
    for index, item in enumerate(chunks):
        item.embedding = vectors[index]

    await vector_index.index_chunks(chunks)
    logger.info("RAG 索引完成：documentId=%s, chunks=%s", document.id, len(chunks))


async def handle_search_index(
    action: str | None, document_id: str | None = None
) -> None:
    """Search 索引：INDEX 写 kh_document，DELETE 删除。"""
    if not document_id:
        logger.warning("忽略缺少 documentId 的 Search 消息：type=%s", action)
        return

    if action == "DELETE":
        await search_index.delete_document(document_id)
        return

    if action == "INDEX":
        documents = await _load_documents([document_id])
        if not documents:
            logger.warning("Search INDEX 文档不存在：documentId=%s", document_id)
            return
        await search_index.index_document(_to_search_document(documents[0]))
        return

    logger.warning("忽略未支持的 Search 消息：type=%s", action)


async def handle_kg_build(
    action: str | None, document_ids: list[str] | None = None
) -> None:
    """KG 建图：BUILD_* 抽实体关系入图，DELETE_* 清理文档子图。"""
    if action == "DELETE_BY_DOC_IDS" and document_ids:
        for document_id in document_ids:
            await graph_build.delete_for_document(document_id)
        return

    if action == "BUILD_ALL":
        documents = await _load_all_published()
    elif action == "BUILD_BY_DOC_IDS" and document_ids:
        documents = await _load_documents(document_ids)
    else:
        documents = []

    if not documents:
        logger.warning("忽略未支持或空的 KG 消息：type=%s", action)
        return

    logger.info("KG 开始建图：type=%s, total=%s", action, len(documents))
    await graph_build.build_batch(documents)


async def update_visibility(doc: Document) -> None:
    """已发布文档改公开 / 所属团队：只同步索引上的可见性字段。"""
    visibility = {
        "isPublic": bool(doc.is_public),
        "teamId": str(doc.team_id) if doc.team_id else None,
        "authorId": str(doc.author_id) if doc.author_id else None,
    }
    document_id = str(doc.id)
    logger.info(
        "同步可见性：documentId=%s, isPublic=%s, teamId=%s",
        document_id,
        visibility["isPublic"],
        visibility["teamId"] or "-",
    )

    await asyncio.gather(
        search_index.update_visibility(document_id, visibility),
        vector_index.update_visibility(document_id, visibility),
        graph_build.update_visibility(document_id, visibility),
    )


def _to_search_document(document: PipelineDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "summary": document.summary,
        "content": document.content,
        "categoryId": document.category_id,
        "tags": document.tags,
        "status": document.status,
        "isPublic": document.is_public,
        "viewCount": document.view_count,
        "likeCount": document.like_count,
        "commentCount": document.comment_count,
        "authorId": document.author_id,
        "teamId": document.team_id,
        "publishTime": document.publish_time,
        "createdAt": document.created_at,
        "updatedAt": document.updated_at,
    }
