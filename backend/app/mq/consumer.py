import logging
from typing import Any

from app.mq import rabbit
from app.mq.constants import KG_GRAPH_QUEUE, RAG_REINDEX_QUEUE, SEARCH_INDEX_QUEUE
from app.pipeline import orchestrator

logger = logging.getLogger(__name__)


async def _handle_rag(payload: dict[str, Any]) -> None:
    logger.info(
        "[RAG] type=%s, taskId=%s, documentIds=%s",
        payload.get("type"),
        payload.get("taskId"),
        payload.get("documentIds") or [],
    )
    await orchestrator.handle_rag_reindex(
        payload.get("type"), payload.get("documentIds")
    )


async def _handle_search(payload: dict[str, Any]) -> None:
    logger.info(
        "[Search] type=%s, taskId=%s, documentId=%s",
        payload.get("type"),
        payload.get("taskId"),
        payload.get("documentId"),
    )
    await orchestrator.handle_search_index(
        payload.get("type"), payload.get("documentId")
    )


async def _handle_kg(payload: dict[str, Any]) -> None:
    logger.info(
        "[KG] type=%s, taskId=%s, documentIds=%s",
        payload.get("type"),
        payload.get("taskId"),
        payload.get("documentIds") or [],
    )
    await orchestrator.handle_kg_build(
        payload.get("type"), payload.get("documentIds")
    )


def register_handlers() -> None:
    rabbit.register_handler(RAG_REINDEX_QUEUE, _handle_rag)
    rabbit.register_handler(SEARCH_INDEX_QUEUE, _handle_search)
    rabbit.register_handler(KG_GRAPH_QUEUE, _handle_kg)
