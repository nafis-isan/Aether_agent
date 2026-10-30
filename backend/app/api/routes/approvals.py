import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openrouter import OpenRouterClient, OpenRouterError
from app.api.routes.chat import provider_http_status
from app.core.security import get_current_user
from app.database import get_db
from app.database.models import (
    AgentCheckpoint,
    AgentRun,
    Approval,
    Conversation,
    Message,
    Task,
    ToolExecution,
    User,
)
from app.schemas.approval import ApprovalDecision, ApprovalRead
from app.schemas.chat import ChatResponse
from app.services.workflow import emit_event, persist_checkpoint
from app.tools.registry import CreateTaskInput

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])
openrouter = OpenRouterClient()


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(
    pending_only: bool = True,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Approval]:
    statement = select(Approval).where(Approval.user_id == user.id)
    if pending_only:
        statement = statement.where(Approval.status == "pending")
    result = await session.execute(statement.order_by(Approval.created_at.desc(), Approval.id))
    return list(result.scalars().all())


@router.post("/{approval_id}/decision", response_model=ChatResponse)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    approval_result = await session.execute(
        select(Approval)
        .where(Approval.id == approval_id, Approval.user_id == user.id)
        .with_for_update()
    )
    approval = approval_result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval has already been decided")

    run_result = await session.execute(
        select(AgentRun).where(AgentRun.id == approval.agent_run_id, AgentRun.user_id == user.id)
    )
    run = run_result.scalar_one_or_none()
    conversation_result = await session.execute(
        select(Conversation).where(
            Conversation.id == approval.conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if run is None or conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    checkpoint_result = await session.execute(
        select(AgentCheckpoint).where(
            AgentCheckpoint.agent_run_id == run.id,
            AgentCheckpoint.checkpoint_key == "approval-pending",
        )
    )
    checkpoint = checkpoint_result.scalar_one_or_none()
    pending_state = checkpoint.state_data if checkpoint is not None else None
    if not pending_state or pending_state.get("pending_approval_id") != approval.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval workflow state is unavailable")

    decided_at = datetime.now(timezone.utc)
    approval.status = "approved" if payload.approve else "rejected"
    approval.decision_note = payload.note
    approval.decided_at = decided_at

    if not payload.approve:
        answer = "Tindakan dibatalkan karena persetujuan ditolak."
        await _save_assistant_reply(
            session,
            conversation_id=conversation.id,
            run_id=run.id,
            answer=answer,
            approval_status="rejected",
        )
        conversation.updated_at = decided_at
        run.status = "completed"
        rejected_state = {**pending_state, "answer": answer, "approval_status": "rejected"}
        await session.commit()
        await persist_checkpoint(session, run_id=run.id, key="worker-completed", state=rejected_state)
        await emit_event(
            session,
            run_id=run.id,
            agent_name=run.selected_agent,
            event_type="approval.denied",
            payload={"approval_id": approval.id, "status": "rejected"},
        )
        await emit_event(
            session,
            run_id=run.id,
            agent_name="aether_core",
            event_type="workflow.completed",
            payload={"status": "completed", "selected_agent": run.selected_agent},
        )
        return ChatResponse(
            conversation_id=conversation.id,
            reply=answer,
            model=run.model_id,
            created_at=decided_at,
            run_id=run.id,
            selected_agent=run.selected_agent,
        )

    task_input = CreateTaskInput.model_validate(approval.tool_arguments)
    task = Task(user_id=user.id, **task_input.model_dump())
    session.add(task)
    await session.flush()
    output = {
        "task": {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        }
    }

    executions_result = await session.execute(
        select(ToolExecution).where(
            ToolExecution.agent_run_id == run.id,
            ToolExecution.tool_name == approval.tool_name,
            ToolExecution.status == "approval_required",
        )
    )
    execution = next(
        (item for item in executions_result.scalars().all() if item.input_data == approval.tool_arguments),
        None,
    )
    if execution is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool execution record is unavailable")
    execution.status = "completed"
    execution.output_data = output
    run.status = "running"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name=run.selected_agent,
        event_type="approval.approved",
        payload={"approval_id": approval.id, "status": "approved"},
    )
    await emit_event(
        session,
        run_id=run.id,
        agent_name=run.selected_agent,
        event_type="tool.completed",
        payload={"tool": approval.tool_name, "status": "completed"},
    )

    continuation_messages = pending_state.get("continuation_messages")
    tool_call = pending_state.get("pending_tool_call")
    if not isinstance(continuation_messages, list) or not isinstance(tool_call, dict):
        run.status = "failed"
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval continuation is unavailable")
    continuation_messages = [
        *continuation_messages,
        {
            "role": "tool",
            "tool_call_id": approval.tool_call_id,
            "content": json.dumps(output, ensure_ascii=True),
        },
    ]
    try:
        completion = await openrouter.complete(
            model=run.model_id,
            messages=continuation_messages,
        )
    except OpenRouterError as exc:
        run.status = "failed"
        await session.commit()
        await emit_event(
            session,
            run_id=run.id,
            agent_name=run.selected_agent,
            event_type="workflow.failed",
            payload={"status": "failed", "error": "The AI provider could not complete this workflow."},
        )
        raise HTTPException(
            status_code=provider_http_status(exc),
            detail=exc.user_message,
        ) from None

    answer = completion["content"]
    result_state = {
        **pending_state,
        "answer": answer,
        "reasoning_details": completion.get("reasoning_details"),
        "usage": completion.get("usage"),
        "approval_status": "approved",
    }
    await persist_checkpoint(session, run_id=run.id, key="worker-completed", state=result_state)
    await _save_assistant_reply(
        session,
        conversation_id=conversation.id,
        run_id=run.id,
        answer=answer,
        approval_status="approved",
    )
    conversation.updated_at = datetime.now(timezone.utc)
    run.status = "completed"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name=run.selected_agent,
        event_type="agent.completed",
        payload={"agent": run.selected_agent, "status": "completed"},
    )
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="workflow.completed",
        payload={"status": "completed", "model": run.model_id, "selected_agent": run.selected_agent},
    )
    return ChatResponse(
        conversation_id=conversation.id,
        reply=answer,
        model=run.model_id,
        created_at=datetime.now(timezone.utc),
        run_id=run.id,
        selected_agent=run.selected_agent,
    )


async def _save_assistant_reply(
    session: AsyncSession,
    *,
    conversation_id: str,
    run_id: str,
    answer: str,
    approval_status: str,
) -> None:
    result = await session.execute(
        select(Message).where(Message.conversation_id == conversation_id, Message.role == "assistant")
    )
    message = next(
        (
            item
            for item in result.scalars().all()
            if item.metadata_json and item.metadata_json.get("agent_run_id") == run_id
        ),
        None,
    )
    now = datetime.now(timezone.utc)
    if message is None:
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            metadata_json={"agent_run_id": run_id, "approval_status": approval_status},
            created_at=now,
        )
        session.add(message)
    else:
        message.content = answer
        metadata = dict(message.metadata_json or {})
        metadata.pop("pending_approval_id", None)
        metadata["approval_status"] = approval_status
        message.metadata_json = metadata
