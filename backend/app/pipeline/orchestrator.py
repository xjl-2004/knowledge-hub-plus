import logging

from app.models import Document

logger = logging.getLogger(__name__)


async def handle_rag_reindex(
    action: str | None, document_ids: list[str] | None = None
) -> None:
    logger.info("RAG 任务：type=%s, documentIds=%s", action, document_ids or [])


async def handle_search_index(
    action: str | None, document_id: str | None = None
) -> None:
    logger.info("Search 任务：type=%s, documentId=%s", action, document_id)


async def handle_kg_build(
    action: str | None, document_ids: list[str] | None = None
) -> None:
    logger.info("KG 任务：type=%s, documentIds=%s", action, document_ids or [])


async def update_visibility(doc: Document) -> None:
    logger.info(
        "同步可见性：documentId=%s, isPublic=%s, teamId=%s",
        doc.id,
        doc.is_public,
        doc.team_id or "-",
    )
