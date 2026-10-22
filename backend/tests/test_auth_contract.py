"""认证接口契约：未授权与参数校验的错误结构。"""


def test_me_without_token_returns_401(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"message"}
    assert isinstance(body["message"], str)


def test_login_without_credentials_returns_400(client):
    response = client.post("/auth/login", json={})

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message"}
    assert isinstance(body["message"], list)
    assert body["message"]


def test_unknown_route_follows_error_shape(client):
    response = client.get("/not-exists")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"message"}
    assert isinstance(body["message"], str)
