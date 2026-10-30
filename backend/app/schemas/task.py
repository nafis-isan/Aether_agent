from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskStatus = Literal["pending", "in_progress", "completed", "cancelled"]
TaskPriority = Literal["low", "medium", "high"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: TaskPriority = "medium"
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task title cannot be blank")
        return value.strip()


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    status: TaskStatus | None = None

    @field_validator("title", mode="before")
    @classmethod
    def reject_blank_title(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Task title cannot be null")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Task title cannot be blank")
        return value.strip()

    @field_validator("priority", "status", mode="before")
    @classmethod
    def reject_null_values(cls, value):
        if value is None:
            raise ValueError("This task field cannot be null")
        return value


class TaskRead(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
