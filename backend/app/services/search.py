"""全文检索。"""

from typing import Any

from app.core.deps import AuthUser
from app.pipeline import search_index
from app.schemas.search import SearchDocumentsDto
from app.services.documents import access_from_user


async def search_documents(
    dto: SearchDocumentsDto, user: AuthUser
) -> dict[str, Any]:
    return await search_index.search_documents(
        keyword=dto.keyword,
        page=dto.page,
        page_size=dto.page_size,
        category_id=dto.category_id,
        author_id=dto.author_id,
        scope=access_from_user(user),
    )
