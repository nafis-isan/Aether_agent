from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MemoryType = Literal["preference", "fact", "context"]


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=2000)
    importance: int = Field(default=3, ge=1, le=5)
    source: str = Field(default="user_entered", min_length=1, max_length=255)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory content cannot be blank")
        return value.strip()

    @field_validator("source")
    @classmethod
    def reject_blank_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory source cannot be blank")
        return value.strip()


class MemoryUpdate(BaseModel):
    memory_type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    importance: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None

    @field_validator("memory_type", "importance", "is_active", mode="before")
    @classmethod
    def reject_null_values(cls, value):
        if value is None:
            raise ValueError("This memory field cannot be null")
        return value

    @field_validator("content", mode="before")
    @classmethod
    def reject_blank_content(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Memory content cannot be null")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Memory content cannot be blank")
        return value.strip()


class MemoryRead(BaseModel):
    id: UUID
    memory_type: MemoryType
    content: str
    importance: int
    source: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
