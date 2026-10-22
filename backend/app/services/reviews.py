import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthUser
from app.core.errors import bad_request, forbidden, not_found
from app.core.snowflake import next_id
from app.models import DocumentReview
from app.schemas.base import iso, page_result
from app.services import documents

logger = logging.getLogger(__name__)

REVIEW_APPROVED = 1
REVIEW_REJECTED = 2


def review_vo(review: DocumentReview) -> dict[str, Any]:
    return {
        "id": str(review.id),
        "documentId": str(review.document_id),
        "reviewerId": str(review.reviewer_id) if review.reviewer_id else None,
        "reviewerName": review.reviewer_name,
        "reviewResult": review.review_result,
        "reviewComment": review.review_comment,
        "beforeStatus": review.before_status,
        "reviewedAt": iso(review.reviewed_at),
        "createdAt": iso(review.created_at),
    }


def can_submit_review(status: int) -> bool:
    return status in (documents.DOCUMENT_DRAFT, documents.DOCUMENT_PUBLISHED)


async def _find_pending_review(
    db: AsyncSession, review_id: str
) -> DocumentReview:
    result = await db.execute(
        select(DocumentReview).where(DocumentReview.id == int(review_id))
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise not_found(f"Review {review_id} not found")
    if review.review_result is not None:
        raise bad_request("该审核任务已处理")
    return review


async def submit_for_review(
    db: AsyncSession, document_id: str, actor: AuthUser | None = None
) -> Any:
    doc = await documents.find_document_or_throw(db, document_id)
    if actor is not None and not documents.can_write_document(doc, actor):
        raise forbidden("无权提交该文档审核")
    if not can_submit_review(doc.status):
        raise bad_request("只有草稿或已发布状态的文档才能提交审核")

    pending = await db.execute(
        select(DocumentReview).where(
            DocumentReview.document_id == int(document_id),
            DocumentReview.review_result.is_(None),
        )
    )
    if pending.scalar_one_or_none() is not None:
        raise bad_request("该文档已有待审核任务")

    before_status = doc.status
    review = DocumentReview(
        id=next_id(),
        document_id=int(document_id),
        before_status=before_status,
    )
    db.add(review)

    doc.status = documents.DOCUMENT_PENDING_REVIEW
    if actor is not None:
        doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()
    await db.commit()

    if before_status == documents.DOCUMENT_PUBLISHED:
        await documents.safe_unpublish(document_id)

    logger.info(
        "文档已提交审核：documentId=%s, reviewId=%s, beforeStatus=%s",
        document_id,
        review.id,
        before_status,
    )
    return doc


async def approve_review(
    db: AsyncSession,
    review_id: str,
    reviewer_id: str,
    reviewer_name: str,
    review_comment: str | None = None,
) -> Any:
    review = await _find_pending_review(db, review_id)

    review.review_result = REVIEW_APPROVED
    review.reviewer_id = int(reviewer_id)
    review.reviewer_name = reviewer_name
    review.review_comment = review_comment
    review.reviewed_at = datetime.now()

    doc = await documents.find_document_or_throw(db, str(review.document_id))
    doc.status = documents.DOCUMENT_PUBLISHED
    doc.publish_time = datetime.now()
    doc.updated_at = datetime.now()
    await db.commit()

    await documents.safe_publish(doc)
    logger.info("审核通过：reviewId=%s, documentId=%s", review_id, doc.id)
    return doc


async def reject_review(
    db: AsyncSession,
    review_id: str,
    review_comment: str,
    reviewer_id: str,
    reviewer_name: str,
) -> Any:
    if not review_comment or not review_comment.strip():
        raise bad_request("驳回意见不能为空")

    review = await _find_pending_review(db, review_id)

    review.review_result = REVIEW_REJECTED
    review.reviewer_id = int(reviewer_id)
    review.reviewer_name = reviewer_name
    review.review_comment = review_comment.strip()
    review.reviewed_at = datetime.now()

    doc = await documents.find_document_or_throw(db, str(review.document_id))
    doc.status = documents.DOCUMENT_DRAFT
    doc.updated_at = datetime.now()
    await db.commit()

    logger.info("审核驳回：reviewId=%s, documentId=%s", review_id, doc.id)
    return doc


async def list_tasks(
    db: AsyncSession,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    conditions = []
    if status is None or status == "pending":
        conditions.append(DocumentReview.review_result.is_(None))
    elif status == "approved":
        conditions.append(DocumentReview.review_result == REVIEW_APPROVED)
    elif status == "rejected":
        conditions.append(DocumentReview.review_result == REVIEW_REJECTED)

    total = (
        await db.execute(
            select(func.count()).select_from(DocumentReview).where(*conditions)
        )
    ).scalar_one()

    result = await db.execute(
        select(DocumentReview)
        .where(*conditions)
        .order_by(DocumentReview.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [review_vo(review) for review in result.scalars().all()]
    return page_result(items, int(total), page, page_size)


async def get_pending_count(db: AsyncSession) -> int:
    count = (
        await db.execute(
            select(func.count())
            .select_from(DocumentReview)
            .where(DocumentReview.review_result.is_(None))
        )
    ).scalar_one()
    return int(count)


async def get_current_review(
    db: AsyncSession, document_id: str
) -> dict[str, Any] | None:
    result = await db.execute(
        select(DocumentReview)
        .where(
            DocumentReview.document_id == int(document_id),
            DocumentReview.review_result.is_(None),
        )
        .order_by(DocumentReview.created_at.desc())
        .limit(1)
    )
    review = result.scalar_one_or_none()
    return review_vo(review) if review else None


async def get_review_history(
    db: AsyncSession, document_id: str
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(DocumentReview)
        .where(DocumentReview.document_id == int(document_id))
        .order_by(DocumentReview.created_at.desc())
    )
    return [review_vo(review) for review in result.scalars().all()]
