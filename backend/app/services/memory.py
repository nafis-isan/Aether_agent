import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Memory

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passcode|api[_ ]?key|secret|access[_ ]?token)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-(?:or-v1-|proj-)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
)


def contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


async def retrieve_relevant_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
) -> list[Memory]:
    words = {word for word in re.findall(r"[\w'-]+", query.casefold()) if len(word) >= 4}
    if not words:
        return []
    result = await session.execute(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.is_active.is_(True))
        .order_by(Memory.importance.desc(), Memory.updated_at.desc())
        .limit(100)
    )
    ranked = []
    for memory in result.scalars().all():
        content_words = set(re.findall(r"[\w'-]+", memory.content.casefold()))
        overlap = len(words & content_words)
        if overlap:
            ranked.append((overlap, memory.importance, memory.updated_at, memory))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [entry[3] for entry in ranked[:limit]]


async def list_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str | None,
    active_only: bool,
) -> Sequence[Memory]:
    statement = select(Memory).where(Memory.user_id == user_id)
    if active_only:
        statement = statement.where(Memory.is_active.is_(True))
    if query:
        statement = statement.where(Memory.content.ilike(f"%{query.strip()}%"))
    result = await session.execute(statement.order_by(Memory.updated_at.desc(), Memory.id))
    return result.scalars().all()
