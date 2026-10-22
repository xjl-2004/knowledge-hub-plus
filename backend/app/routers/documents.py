from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_permissions
from app.schemas.documents import CreateDocumentDto, UpdateDocumentDto
from app.services import documents

router = APIRouter(prefix="/documents", tags=["documents"])
document_list = [Depends(require_permissions("document:list"))]
document_create = [Depends(require_permissions("document:create"))]
document_edit = [Depends(require_permissions("document:edit"))]
document_delete = [Depends(require_permissions("document:delete"))]


@router.post("", dependencies=document_create)
async def create_document(db: DbSession, dto: CreateDocumentDto, user: CurrentUser):
    return await documents.create(db, dto, user)


@router.get("", dependencies=document_list)
async def list_documents(
    db: DbSession,
    user: CurrentUser,
    title: str | None = Query(None),
    category_id: str | None = Query(None, alias="categoryId"),
    team_id: str | None = Query(None, alias="teamId"),
    author_id: str | None = Query(None, alias="authorId"),
    status: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
):
    return await documents.find_all(
        db,
        user,
        title=title,
        category_id=category_id,
        team_id=team_id,
        author_id=author_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.put("/{document_id}/publish", dependencies=document_edit)
async def publish_document(document_id: str, db: DbSession, user: CurrentUser):
    return await documents.publish(db, document_id, user)


@router.put("/{document_id}/archive", dependencies=document_edit)
async def archive_document(document_id: str, db: DbSession, user: CurrentUser):
    return await documents.archive(db, document_id, user)


@router.put("/{document_id}/save-draft", dependencies=document_edit)
async def save_document_as_draft(
    document_id: str, db: DbSession, user: CurrentUser
):
    return await documents.save_as_draft(db, document_id, user)


@router.get("/{document_id}", dependencies=document_list)
async def get_document(document_id: str, db: DbSession, user: CurrentUser):
    return await documents.find_one(db, document_id, True, user)


@router.patch("/{document_id}", dependencies=document_edit)
async def update_document(
    document_id: str, db: DbSession, dto: UpdateDocumentDto, user: CurrentUser
):
    return await documents.update(db, document_id, dto, user)


@router.delete("/{document_id}", dependencies=document_delete)
async def delete_document(document_id: str, db: DbSession, user: CurrentUser):
    return await documents.remove(db, document_id, user)
