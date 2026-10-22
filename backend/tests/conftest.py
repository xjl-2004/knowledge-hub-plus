"""接口契约测试公共配置。"""

import os

# 测试不依赖外部服务与外部模型
os.environ["OPENAI_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["DASHSCOPE_API_KEY"] = ""
os.environ["BOCHA_API_KEY"] = ""
os.environ["RUSTFS_ENABLED"] = "false"
os.environ["RABBITMQ_ENABLED"] = "false"
os.environ["ELASTICSEARCH_ENABLED"] = "false"
os.environ["NEO4J_ENABLED"] = "false"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import AuthUser
from app.main import create_app


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_user() -> AuthUser:
    return AuthUser(
        user_id="1",
        username="tester",
        real_name="Tester",
        email="tester@example.com",
        avatar=None,
        roles=["ROLE_USER"],
        permissions=["search"],
        team_ids=[],
    )
