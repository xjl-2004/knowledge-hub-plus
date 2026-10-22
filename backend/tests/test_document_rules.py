"""文档状态机与审核流转规则。"""

from app.models import Document
from app.services import documents, reviews


def _document(**kwargs) -> Document:
    data = {
        "id": 1,
        "title": "制度",
        "content_id": "content-1",
        "author_id": 1,
        "status": documents.DOCUMENT_DRAFT,
        "is_public": False,
    }
    data.update(kwargs)
    return Document(**data)


def test_publish_allowed_statuses():
    allowed = {
        documents.DOCUMENT_DRAFT,
        documents.DOCUMENT_PUBLISHED,
        documents.DOCUMENT_ARCHIVED,
        documents.DOCUMENT_PENDING_REVIEW,
    }
    for status in allowed:
        assert documents.can_publish_from(status) is True
    assert documents.can_publish_from(9) is False


def test_edit_content_only_for_editable_statuses():
    for status in (
        documents.DOCUMENT_DRAFT,
        documents.DOCUMENT_PUBLISHED,
        documents.DOCUMENT_ARCHIVED,
    ):
        assert documents.can_edit_content(status) is True
    assert documents.can_edit_content(documents.DOCUMENT_PENDING_REVIEW) is False


def test_archive_requires_published_status():
    assert documents.can_archive(documents.DOCUMENT_PUBLISHED) is True
    assert documents.can_archive(documents.DOCUMENT_DRAFT) is False
    assert documents.can_archive(documents.DOCUMENT_ARCHIVED) is False


def test_submit_review_from_draft_or_published():
    assert reviews.can_submit_review(documents.DOCUMENT_DRAFT) is True
    assert reviews.can_submit_review(documents.DOCUMENT_PUBLISHED) is True
    assert reviews.can_submit_review(documents.DOCUMENT_PENDING_REVIEW) is False
    assert reviews.can_submit_review(documents.DOCUMENT_ARCHIVED) is False


def test_read_visibility_follows_public_team_and_author(auth_user):
    scope = documents.DocumentAccessScope(
        unrestricted=False, user_id="1", team_ids=["7"]
    )
    public = _document(
        is_public=True, author_id=9, status=documents.DOCUMENT_PUBLISHED
    )
    team = _document(
        is_public=False, team_id=7, author_id=9, status=documents.DOCUMENT_PUBLISHED
    )
    other_team = _document(
        is_public=False, team_id=8, author_id=9, status=documents.DOCUMENT_PUBLISHED
    )
    draft = _document(is_public=True, status=documents.DOCUMENT_DRAFT)

    assert documents.can_read_document(public, scope) is True
    assert documents.can_read_document(team, scope) is True
    assert documents.can_read_document(other_team, scope) is False
    assert documents.can_read_document(draft, scope) is True
    assert documents.can_read_document(_document(author_id=9), scope) is False


def test_admin_scope_can_read_everything():
    scope = documents.DocumentAccessScope(
        unrestricted=True, user_id="1", team_ids=[]
    )
    assert documents.can_read_document(_document(author_id=9), scope) is True


def test_write_requires_author_or_admin(auth_user):
    own = _document(author_id=1)
    other = _document(author_id=9)

    assert documents.can_write_document(own, auth_user) is True
    assert documents.can_write_document(other, auth_user) is False

    admin = documents.AuthUser(
        user_id="2",
        username="admin",
        real_name=None,
        email=None,
        avatar=None,
        roles=["ROLE_ADMIN"],
        permissions=[],
        team_ids=[],
    )
    assert documents.can_write_document(other, admin) is True


def test_content_summary_and_word_count():
    assert documents.build_content_summary("  多余   空白  ") == "多余 空白"
    long_text = "字" * 205
    summary = documents.build_content_summary(long_text)
    assert summary == "字" * 200 + "..."

    assert documents.count_words("") == 0
    assert documents.count_words("知识库 knowledge hub") == 5
