import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bson import ObjectId
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthUser
from app.core.errors import bad_request, forbidden, not_found
from app.core.snowflake import next_id
from app.db import mongo as mongo_db
from app.models import Document
from app.schemas.base import iso, page_result
from app.schemas.documents import CreateDocumentDto, UpdateDocumentDto
from app.services import accounts

logger = logging.getLogger(__name__)

DOCUMENT_DRAFT = 0
DOCUMENT_PUBLISHED = 1
DOCUMENT_ARCHIVED = 2
DOCUMENT_PENDING_REVIEW = 3

_UNSET = object()


@dataclass
class DocumentAccessScope:
    unrestricted: bool
    user_id: str
    team_ids: list[str] = field(default_factory=list)


def access_from_user(user: AuthUser) -> DocumentAccessScope:
    roles = user.roles or []
    return DocumentAccessScope(
        unrestricted=accounts.ROLE_ADMIN in roles or accounts.ROLE_REVIEWER in roles,
        user_id=user.user_id,
        team_ids=list(user.team_ids or []),
    )


def can_read_document(doc: Document, scope: DocumentAccessScope) -> bool:
    if scope.unrestricted:
        return True
    if doc.author_id and str(doc.author_id) == scope.user_id:
        return True
    if doc.status != DOCUMENT_PUBLISHED:
        return False
    if doc.is_public:
        return True
    return bool(doc.team_id and str(doc.team_id) in scope.team_ids)


def can_write_document(doc: Document, user: AuthUser) -> bool:
    if accounts.ROLE_ADMIN in (user.roles or []):
        return True
    return bool(doc.author_id and str(doc.author_id) == user.user_id)


def assert_writable(doc: Document, actor: AuthUser) -> None:
    if not can_write_document(doc, actor):
        raise forbidden("无权修改该文档")


def can_publish_from(status: int) -> bool:
    return status in (
        DOCUMENT_DRAFT,
        DOCUMENT_PUBLISHED,
        DOCUMENT_ARCHIVED,
        DOCUMENT_PENDING_REVIEW,
    )


def can_edit_content(status: int) -> bool:
    return status in (DOCUMENT_DRAFT, DOCUMENT_PUBLISHED, DOCUMENT_ARCHIVED)


def can_archive(status: int) -> bool:
    return status == DOCUMENT_PUBLISHED


def require_approval() -> bool:
    return settings.document_require_approval


def build_content_summary(content: str, max_len: int = 200) -> str:
    trimmed = re.sub(r"\s+", " ", content.strip())
    if len(trimmed) <= max_len:
        return trimmed
    return f"{trimmed[:max_len]}..."


def count_words(content: str) -> int:
    trimmed = content.strip()
    if not trimmed:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", trimmed))
    latin = len(re.sub(r"[\u4e00-\u9fff]", " ", trimmed).split())
    return cjk + latin


def _object_id(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except Exception:
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def document_vo(doc: Document, content: Any = _UNSET) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(doc.id),
        "title": doc.title,
        "contentId": doc.content_id,
        "summary": doc.summary,
        "categoryId": str(doc.category_id) if doc.category_id else None,
        "teamId": str(doc.team_id) if doc.team_id else None,
        "authorId": str(doc.author_id) if doc.author_id else None,
        "coverImage": doc.cover_image,
        "tags": doc.tags,
        "status": doc.status,
        "remark": doc.remark,
        "viewCount": doc.view_count,
        "likeCount": doc.like_count,
        "commentCount": doc.comment_count,
        "favouriteCount": doc.favourite_count,
        "wordCount": doc.word_count,
        "publishTime": iso(doc.publish_time),
        "isPublic": doc.is_public,
        "createdAt": iso(doc.created_at),
        "updatedAt": iso(doc.updated_at),
        "createBy": str(doc.create_by) if doc.create_by else None,
        "updateBy": str(doc.update_by) if doc.update_by else None,
        "deleted": doc.deleted,
    }
    if content is not _UNSET:
        data["content"] = content or ""
    return data


async def find_document_or_throw(db: AsyncSession, document_id: str) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == int(document_id), Document.deleted.is_(False)
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise not_found(f"Document {document_id} not found")
    return doc


async def _load_content(content_id: str) -> str:
    oid = _object_id(content_id)
    if oid is None:
        return ""
    record = await mongo_db.document_content_collection().find_one(
        {"_id": oid, "deleted": False}
    )
    return (record or {}).get("content") or ""


async def create(
    db: AsyncSession, dto: CreateDocumentDto, actor: AuthUser
) -> dict[str, Any]:
    requested_status = DOCUMENT_DRAFT if dto.status is None else dto.status
    if requested_status not in (DOCUMENT_DRAFT, DOCUMENT_PUBLISHED):
        raise bad_request("创建文档仅允许草稿或已发布状态")
    if requested_status == DOCUMENT_PUBLISHED and require_approval():
        raise bad_request("开启审核时请先创建草稿，再提交发布/审核")

    document_id = next_id()
    word_count = count_words(dto.content)
    content_summary = (
        dto.summary if dto.summary is not None else build_content_summary(dto.content)
    )

    collection = mongo_db.document_content_collection()
    inserted = await collection.insert_one(
        {
            "documentId": str(document_id),
            "content": dto.content,
            "contentLength": len(dto.content),
            "contentSummary": content_summary,
            "version": 1,
            "deleted": False,
        }
    )
    content_id = str(inserted.inserted_id)

    doc = Document(
        id=document_id,
        title=dto.title,
        content_id=content_id,
        summary=dto.summary,
        category_id=_int_or_none(dto.category_id),
        team_id=_int_or_none(dto.team_id),
        author_id=int(actor.user_id),
        cover_image=dto.cover_image,
        tags=dto.tags,
        status=requested_status,
        remark=dto.remark,
        is_public=dto.is_public if dto.is_public is not None else False,
        word_count=word_count,
        publish_time=datetime.now() if requested_status == DOCUMENT_PUBLISHED else None,
        create_by=int(actor.user_id),
        update_by=int(actor.user_id),
        deleted=False,
    )
    db.add(doc)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await collection.delete_one({"_id": inserted.inserted_id})
        raise

    if requested_status == DOCUMENT_PUBLISHED:
        await _safe_publish(doc)

    return document_vo(doc, dto.content)


async def find_all(
    db: AsyncSession,
    user: AuthUser,
    title: str | None = None,
    category_id: str | None = None,
    team_id: str | None = None,
    author_id: str | None = None,
    status: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    scope = access_from_user(user)

    conditions = [Document.deleted.is_(False)]
    if not scope.unrestricted:
        if scope.team_ids:
            conditions.append(
                or_(
                    Document.author_id == int(scope.user_id),
                    and_(
                        Document.status == DOCUMENT_PUBLISHED,
                        or_(
                            Document.is_public.is_(True),
                            Document.team_id.in_([int(item) for item in scope.team_ids]),
                        ),
                    ),
                )
            )
        else:
            conditions.append(
                or_(
                    Document.author_id == int(scope.user_id),
                    and_(
                        Document.status == DOCUMENT_PUBLISHED,
                        Document.is_public.is_(True),
                    ),
                )
            )

    if title:
        conditions.append(Document.title.ilike(f"%{title}%"))
    if category_id:
        conditions.append(Document.category_id == int(category_id))
    if team_id:
        conditions.append(Document.team_id == int(team_id))
    if author_id:
        conditions.append(Document.author_id == int(author_id))
    if status is not None:
        conditions.append(Document.status == status)

    total = (
        await db.execute(select(func.count()).select_from(Document).where(*conditions))
    ).scalar_one()

    rows = await db.execute(
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [document_vo(doc) for doc in rows.scalars().all()]
    return page_result(items, int(total), page, page_size)


async def find_one(
    db: AsyncSession,
    document_id: str,
    with_content: bool = True,
    user: AuthUser | None = None,
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    if user is not None and not can_read_document(doc, access_from_user(user)):
        raise forbidden("无权查看该文档")
    if not with_content:
        return document_vo(doc)
    return document_vo(doc, await _load_content(doc.content_id))


async def update(
    db: AsyncSession, document_id: str, dto: UpdateDocumentDto, actor: AuthUser
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    assert_writable(doc, actor)

    old_status = doc.status
    old_is_public = doc.is_public
    old_team_id = doc.team_id
    data = dto.model_dump(exclude_unset=True)

    if doc.status == DOCUMENT_PENDING_REVIEW:
        if "content" in data or "title" in data:
            raise bad_request("审核中的文档不可编辑")
    elif not can_edit_content(doc.status):
        raise bad_request("当前文档状态不允许编辑")

    if "status" in data and data["status"] != doc.status:
        if data["status"] == DOCUMENT_DRAFT and doc.status == DOCUMENT_PUBLISHED:
            doc.status = DOCUMENT_DRAFT
        else:
            raise bad_request(
                "请使用 publish / archive / save-draft / 审核接口变更文档状态"
            )

    content_changed = False
    new_content: str | None = None
    collection = mongo_db.document_content_collection()
    content_oid = _object_id(doc.content_id)

    if "content" in data and data["content"] is not None:
        content_changed = True
        new_content = data["content"]
        content_summary = data.get("summary")
        if content_summary is None:
            content_summary = build_content_summary(new_content)
        result = await collection.update_one(
            {"_id": content_oid, "deleted": False},
            {
                "$set": {
                    "content": new_content,
                    "contentLength": len(new_content),
                    "contentSummary": content_summary,
                },
                "$inc": {"version": 1},
            },
        )
        if result.matched_count == 0:
            raise bad_request(f"Document content {doc.content_id} not found")
        doc.word_count = count_words(new_content)
    elif "summary" in data:
        await collection.update_one(
            {"_id": content_oid, "deleted": False},
            {"$set": {"contentSummary": data["summary"]}},
        )

    if "title" in data:
        doc.title = data["title"]
    if "summary" in data:
        doc.summary = data["summary"]
    if "category_id" in data:
        doc.category_id = _int_or_none(data["category_id"])
    if "team_id" in data:
        doc.team_id = _int_or_none(data["team_id"])
    if "cover_image" in data:
        doc.cover_image = data["cover_image"]
    if "tags" in data:
        doc.tags = data["tags"]
    if "remark" in data:
        doc.remark = data["remark"]
    if "is_public" in data:
        doc.is_public = data["is_public"]
    doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()

    await db.commit()

    final_content = (
        new_content if content_changed else await _load_content(doc.content_id)
    )
    visibility_changed = doc.is_public != old_is_public or doc.team_id != old_team_id
    await _sync_after_update(
        doc, old_status, content_changed, visibility_changed
    )
    return document_vo(doc, final_content)


async def publish(
    db: AsyncSession, document_id: str, actor: AuthUser
) -> dict[str, Any]:
    logger.info("发布文档：documentId=%s", document_id)
    doc = await find_document_or_throw(db, document_id)
    assert_writable(doc, actor)

    if not can_publish_from(doc.status):
        raise bad_request("当前文档状态不允许发布")
    if doc.status == DOCUMENT_PENDING_REVIEW:
        raise bad_request("文档审核中，请等待审核结果")

    if require_approval() and doc.status in (DOCUMENT_DRAFT, DOCUMENT_PUBLISHED):
        previous_status = doc.status
        doc.status = DOCUMENT_PENDING_REVIEW
        doc.update_by = int(actor.user_id)
        doc.updated_at = datetime.now()
        await db.commit()
        if previous_status == DOCUMENT_PUBLISHED:
            await _safe_unpublish(document_id)
        content = await _load_content(doc.content_id)
        return document_vo(doc, content)

    return await direct_publish(db, document_id, actor)


async def direct_publish(
    db: AsyncSession, document_id: str, actor: AuthUser | None = None
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    if doc.status not in (
        DOCUMENT_DRAFT,
        DOCUMENT_PUBLISHED,
        DOCUMENT_ARCHIVED,
        DOCUMENT_PENDING_REVIEW,
    ):
        raise bad_request("当前文档状态不允许发布")

    doc.status = DOCUMENT_PUBLISHED
    doc.publish_time = datetime.now()
    if actor is not None:
        doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()
    await db.commit()

    content = await _load_content(doc.content_id)
    await _safe_publish(doc)
    logger.info("文档发布成功：documentId=%s", document_id)
    return document_vo(doc, content)


async def archive(
    db: AsyncSession, document_id: str, actor: AuthUser
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    assert_writable(doc, actor)
    if not can_archive(doc.status):
        raise bad_request("只有已发布文档可以归档")

    doc.status = DOCUMENT_ARCHIVED
    doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()
    await db.commit()
    await _safe_unpublish(document_id)
    logger.info("文档已归档：documentId=%s", document_id)
    return document_vo(doc)


async def save_as_draft(
    db: AsyncSession, document_id: str, actor: AuthUser
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    assert_writable(doc, actor)
    if doc.status != DOCUMENT_PUBLISHED:
        raise bad_request("只有已发布文档可以保存为草稿")

    doc.status = DOCUMENT_DRAFT
    doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()
    await db.commit()
    await _safe_unpublish(document_id)
    logger.info("文档已保存为草稿：documentId=%s", document_id)
    return document_vo(doc)


async def remove(
    db: AsyncSession, document_id: str, actor: AuthUser
) -> dict[str, Any]:
    doc = await find_document_or_throw(db, document_id)
    assert_writable(doc, actor)

    if doc.status == DOCUMENT_PUBLISHED:
        await _safe_unpublish(document_id)

    doc.deleted = True
    doc.update_by = int(actor.user_id)
    doc.updated_at = datetime.now()
    await db.commit()

    content_oid = _object_id(doc.content_id)
    if content_oid is not None:
        await mongo_db.document_content_collection().update_one(
            {"_id": content_oid}, {"$set": {"deleted": True}}
        )
    return {"id": str(doc.id), "deleted": True}


async def _sync_after_update(
    doc: Document,
    old_status: int,
    content_changed: bool,
    visibility_changed: bool,
) -> None:
    was_published = old_status == DOCUMENT_PUBLISHED
    is_published = doc.status == DOCUMENT_PUBLISHED

    if was_published and not is_published:
        await _safe_unpublish(str(doc.id))
        return

    if is_published and content_changed and not require_approval():
        await _safe_publish(doc)
        return

    if is_published and visibility_changed:
        await _safe_update_visibility(doc)


async def _safe_publish(doc: Document) -> None:
    logger.info("文档索引同步：documentId=%s", doc.id)


async def _safe_unpublish(document_id: str) -> None:
    logger.info("文档索引清理：documentId=%s", document_id)


async def _safe_update_visibility(doc: Document) -> None:
    logger.info("文档可见性同步：documentId=%s", doc.id)
