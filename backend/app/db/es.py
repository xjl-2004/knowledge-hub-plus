import logging

from elasticsearch import AsyncElasticsearch

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AsyncElasticsearch | None = None


def get_es() -> AsyncElasticsearch | None:
    global _client
    if not settings.elasticsearch_enabled:
        return None
    if _client is None:
        _client = AsyncElasticsearch(settings.elasticsearch_node, request_timeout=10)
    return _client


async def ping() -> bool:
    client = get_es()
    if client is None:
        return False
    return bool(await client.ping())


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
