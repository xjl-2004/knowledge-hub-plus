import logging

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver | None:
    global _driver
    if not settings.neo4j_enabled:
        return None
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def ping() -> bool:
    driver = get_driver()
    if driver is None:
        return False
    await driver.verify_connectivity()
    return True


async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
