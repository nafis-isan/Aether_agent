from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.database.models import Memory, User
from app.schemas.memory import MemoryCreate, MemoryRead, MemoryUpdate
from app.services.memory import contains_secret, list_user_memories

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


@router.get("", response_model=list[MemoryRead])
async def list_memories(
    query: str | None = Query(default=None, max_length=100),
    active_only: bool = False,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Memory]:
    return list(
        await list_user_memories(
            session,
            user_id=user.id,
            query=query,
            active_only=active_only,
        )
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    if contains_secret(payload.content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Credential-like information cannot be saved as memory",
        )
    memory = Memory(
        user_id=user.id,
        memory_type=payload.memory_type,
        content=payload.content,
        importance=payload.importance,
        source=payload.source,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Memory:
    result = await session.execute(
        select(Memory).where(Memory.id == str(memory_id), Memory.user_id == user.id)
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    changes = payload.model_dump(exclude_unset=True)
    if "content" in changes and changes["content"] is not None and contains_secret(changes["content"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Credential-like information cannot be saved as memory",
        )
    for key, value in changes.items():
        setattr(memory, key, value)
    await session.commit()
    await session.refresh(memory)
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    result = await session.execute(
        select(Memory).where(Memory.id == str(memory_id), Memory.user_id == user.id)
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    await session.delete(memory)
    await session.commit()
