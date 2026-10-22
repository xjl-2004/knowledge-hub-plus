import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.db import es as es_db
from app.db import mongo as mongo_db
from app.db import neo4j as neo4j_db
from app.db import redis as redis_db
from app.db import s3 as s3_db
from app.routers import auth, permissions, roles, teams, users

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging(settings.debug)
    try:
        await s3_db.ensure_bucket()
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("对象存储初始化跳过：%s", exc)
    yield
    await mongo_db.close()
    await redis_db.close()
    await es_db.close()
    await neo4j_db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    register_exception_handlers(app)

    for router in (auth.router, users.router, roles.router, permissions.router, teams.router):
        app.include_router(router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
