"""Single shared Motor client. MongoDB is the only state at runtime."""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import get_settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            uuidRepresentation="standard",
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            maxPoolSize=50,
            minPoolSize=2,
            retryWrites=True,
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[get_settings().CSX_DEMO_DB]


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
