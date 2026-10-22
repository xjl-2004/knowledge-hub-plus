from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
        )
    return _client


async def ping() -> bool:
    await get_redis().ping()
    return True


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
