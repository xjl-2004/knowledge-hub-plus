import asyncio
import logging
import uuid

from app.mq import rabbit
from app.mq.constants import (
    KG_GRAPH_EXCHANGE,
    KG_RK_BUILD_BY_IDS,
    KG_RK_DELETE,
    RAG_REINDEX_EXCHANGE,
    RAG_RK_BY_IDS,
    RAG_RK_DELETE,
    SEARCH_INDEX_EXCHANGE,
    SEARCH_RK_DELETE,
    SEARCH_RK_INDEX,
)

logger = logging.getLogger(__name__)


async def after_publish(document) -> None:
    """发布成功后并行投递 RAG / Search / KG 任务。"""
    document_id = str(document.id)
    await asyncio.gather(
        _trigger_rag_reindex(document_id),
        _trigger_search_index(document_id),
        _trigger_kg_build(document_id),
    )


async def after_unpublish(document_id: str) -> None:
    """归档 / 删除后通知三类索引清理。"""
    await asyncio.gather(
        _trigger_rag_delete(document_id),
        _trigger_search_delete(document_id),
        _trigger_kg_delete(document_id),
    )


async def _trigger_rag_reindex(document_id: str) -> None:
    task_id = str(uuid.uuid4())
    ok = await rabbit.publish(
        RAG_REINDEX_EXCHANGE,
        RAG_RK_BY_IDS,
        {"taskId": task_id, "type": "BY_DOC_IDS", "documentIds": [document_id]},
    )
    logger.info(
        "RAG 重建索引%s：documentId=%s, taskId=%s",
        "已投递" if ok else "投递失败",
        document_id,
        task_id,
    )


async def _trigger_rag_delete(document_id: str) -> None:
    await rabbit.publish(
        RAG_REINDEX_EXCHANGE,
        RAG_RK_DELETE,
        {
            "taskId": str(uuid.uuid4()),
            "type": "DELETE_BY_DOC_IDS",
            "documentIds": [document_id],
        },
    )


async def _trigger_search_index(document_id: str) -> None:
    task_id = str(uuid.uuid4())
    ok = await rabbit.publish(
        SEARCH_INDEX_EXCHANGE,
        SEARCH_RK_INDEX,
        {"taskId": task_id, "type": "INDEX", "documentId": document_id},
    )
    logger.info(
        "ES 搜索索引%s：documentId=%s, taskId=%s",
        "已投递" if ok else "投递失败",
        document_id,
        task_id,
    )


async def _trigger_search_delete(document_id: str) -> None:
    await rabbit.publish(
        SEARCH_INDEX_EXCHANGE,
        SEARCH_RK_DELETE,
        {"taskId": str(uuid.uuid4()), "type": "DELETE", "documentId": document_id},
    )


async def _trigger_kg_build(document_id: str) -> None:
    task_id = str(uuid.uuid4())
    ok = await rabbit.publish(
        KG_GRAPH_EXCHANGE,
        KG_RK_BUILD_BY_IDS,
        {
            "taskId": task_id,
            "type": "BUILD_BY_DOC_IDS",
            "documentIds": [document_id],
        },
    )
    logger.info(
        "KG 建图%s：documentId=%s, taskId=%s",
        "已投递" if ok else "投递失败",
        document_id,
        task_id,
    )


async def _trigger_kg_delete(document_id: str) -> None:
    await rabbit.publish(
        KG_GRAPH_EXCHANGE,
        KG_RK_DELETE,
        {
            "taskId": str(uuid.uuid4()),
            "type": "DELETE_BY_DOC_IDS",
            "documentIds": [document_id],
        },
    )
