"""RBAC 接口契约：缺少权限时返回 403 与统一错误结构。"""

from app.core.deps import AuthUser, get_current_user


def _override_user(app, permissions: list[str], roles: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        user_id="1",
        username="tester",
        real_name="Tester",
        email="tester@example.com",
        avatar=None,
        roles=roles or ["ROLE_USER"],
        permissions=permissions,
        team_ids=[],
    )


def test_create_document_without_permission_returns_403(client, app):
    _override_user(app, [])
    try:
        response = client.post(
            "/documents", json={"title": "合同", "content": "正文"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {"message": "无权限：document:create"}


def test_search_without_permission_returns_403(client, app):
    _override_user(app, ["document:list"])
    try:
        response = client.post("/search", json={"keyword": "制度"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"message"}
    assert body["message"] == "无权限：search"


def test_review_tasks_require_reviewer_role(client, app):
    _override_user(app, ["document:review"], roles=["ROLE_USER"])
    try:
        response = client.get("/documents/reviews/tasks")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"message"}
    assert "需要角色" in body["message"]
