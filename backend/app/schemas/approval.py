from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

ApprovalStatus = Literal["pending", "approved", "rejected"]


class ApprovalRead(BaseModel):
    id: UUID
    agent_run_id: UUID
    conversation_id: UUID
    tool_name: str
    tool_arguments: dict
    status: ApprovalStatus
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)
