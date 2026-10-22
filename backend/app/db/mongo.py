from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongo_db]


def document_content_collection():
    return get_db()["document_content"]


async def ping() -> bool:
    await get_client().admin.command("ping")
    return True


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
