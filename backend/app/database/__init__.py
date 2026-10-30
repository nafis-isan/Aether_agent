from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def mask_database_url(url: str) -> str:
    if "://" not in url:
        return url

    parsed = urlsplit(url)
    username = parsed.username or ""
    password = parsed.password or ""

    if username and password:
        netloc = parsed.hostname or "localhost"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, f"{username}:***@{netloc}", parsed.path, parsed.query, parsed.fragment))

    return url


engine = create_async_engine(settings.database_url, echo=False, pool_recycle=1800)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_database_status() -> dict:
    masked_url = mask_database_url(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "connected", "dialect": "mysql", "database_url": masked_url}
    except Exception as exc:  # pragma: no cover - runtime dependency check
        return {
            "status": "unavailable",
            "dialect": "mysql",
            "database_url": masked_url,
            "error": str(exc),
        }
