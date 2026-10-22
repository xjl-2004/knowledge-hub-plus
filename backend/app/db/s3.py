import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aioboto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

_session = aioboto3.Session()


@asynccontextmanager
async def client() -> AsyncIterator[object]:
    async with _session.client(
        "s3",
        endpoint_url=settings.rustfs_endpoint,
        aws_access_key_id=settings.rustfs_access_key,
        aws_secret_access_key=settings.rustfs_secret_key,
        region_name=settings.rustfs_region,
    ) as s3:
        yield s3


async def ensure_bucket() -> None:
    if not settings.rustfs_enabled:
        return
    try:
        async with client() as s3:
            try:
                await s3.head_bucket(Bucket=settings.rustfs_bucket)
            except ClientError:
                await s3.create_bucket(Bucket=settings.rustfs_bucket)
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("对象存储不可用：%s", exc)


async def put_object(key: str, body: bytes, content_type: str | None = None) -> str:
    async with client() as s3:
        await s3.put_object(
            Bucket=settings.rustfs_bucket,
            Key=key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
        )
    return public_url(key)


def public_url(key: str) -> str:
    return f"{settings.rustfs_public_url.rstrip('/')}/{settings.rustfs_bucket}/{key}"


async def ping() -> bool:
    if not settings.rustfs_enabled:
        return False
    async with client() as s3:
        await s3.head_bucket(Bucket=settings.rustfs_bucket)
    return True
