import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import WorkflowState, run_workflow
from app.ai.model_router import resolve_model
from app.ai.openrouter import OpenRouterClient, OpenRouterError
from app.core.security import get_current_user
from app.database import get_db
from app.database.models import (
    AgentCheckpoint,
    AgentEvent,
    AgentRun,
    Approval,
    Conversation,
    Message,
    ToolExecution,
    User,
)
from app.schemas.chat import ChatRequest, ChatResponse, ConversationRead, MessageRead
from app.services.memory import retrieve_relevant_memories
from app.services.workflow import emit_event

router = APIRouter(prefix="/api/v1", tags=["chat"])
openrouter = OpenRouterClient()
MAX_CONTEXT_MESSAGES = 20


def provider_http_status(error: OpenRouterError) -> int:
    if error.code == "configuration_error":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code == "browser_unavailable":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code == "invalid_api_key":
        return status.HTTP_502_BAD_GATEWAY
    if error.code == "rate_limited":
        return status.HTTP_429_TOO_MANY_REQUESTS
    if error.code == "timeout":
        return status.HTTP_504_GATEWAY_TIMEOUT
    if error.code == "model_unavailable":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code in {"provider_unavailable", "invalid_response", "provider_error"}:
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_502_BAD_GATEWAY


@router.post("/chat", response_model=ChatResponse)
async def send_chat_message(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    if payload.conversation_id is None:
        conversation = Conversation(
            id=str(uuid4()),
            user_id=user.id,
            title=payload.message.strip().splitlines()[0][:80] or "New conversation",
        )
        session.add(conversation)
        await session.flush()
    else:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == str(payload.conversation_id),
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    history_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )
    history = list(reversed(history_result.scalars().all()))
    now = datetime.now(timezone.utc)
    user_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        role="user",
        content=payload.message,
        created_at=now,
    )
    session.add(user_message)

    model_messages: list[dict] = [
        {
            "role": message.role,
            "content": message.content,
            **(
                {"reasoning_details": message.metadata_json["reasoning_details"]}
                if message.role == "assistant"
                and message.metadata_json
                and "reasoning_details" in message.metadata_json
                else {}
            ),
        }
        for message in history
    ]
    model_messages.append({"role": "user", "content": payload.message})
    memories = await retrieve_relevant_memories(
        session,
        user_id=user.id,
        query=payload.message,
    )
    model_id = resolve_model(payload.model_role)
    run = AgentRun(
        id=str(uuid4()),
        conversation_id=conversation.id,
        user_id=user.id,
        status="running",
        selected_agent="aether_core",
        model_id=model_id,
        state_snapshot={
            "run_id": "",
            "conversation_id": conversation.id,
            "user_id": user.id,
            "request": payload.message,
            "model_role": payload.model_role,
            "messages": model_messages,
            "memories": [memory.content for memory in memories],
            "step_count": 0,
        },
    )
    run.state_snapshot["run_id"] = run.id
    session.add(run)
    await session.commit()

    state: WorkflowState = {
        "run_id": run.id,
        "conversation_id": conversation.id,
        "user_id": user.id,
        "request": payload.message,
        "model_role": payload.model_role,
        "messages": model_messages,
        "memories": [memory.content for memory in memories],
        "step_count": 0,
    }
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="agent.started",
        payload={"agent": "aether_core", "status": "started"},
    )
    try:
        completion = await run_workflow(session=session, client=openrouter, run=run, state=state)
    except OpenRouterError as exc:
        raise HTTPException(
            status_code=provider_http_status(exc),
            detail=exc.user_message,
        ) from None

    assistant_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        role="assistant",
        content=completion["answer"],
        metadata_json={
            "model": completion["model_id"],
            "reasoning_details": completion.get("reasoning_details"),
            "usage": completion.get("usage"),
            "agent": completion["selected_agent"],
            "agent_run_id": run.id,
            "pending_approval_id": completion.get("pending_approval_id"),
        },
        created_at=datetime.now(timezone.utc),
    )
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(assistant_message)
    is_waiting_approval = completion.get("pending_approval_id") is not None
    run.status = "waiting_approval" if is_waiting_approval else "completed"
    await session.commit()
    if not is_waiting_approval:
        await emit_event(
            session,
            run_id=run.id,
            agent_name="aether_core",
            event_type="workflow.completed",
            payload={
                "status": "completed",
                "model": completion["model_id"],
                "selected_agent": completion["selected_agent"],
            },
        )

    return ChatResponse(
        conversation_id=conversation.id,
        reply=assistant_message.content,
        model=completion["model_id"],
        created_at=assistant_message.created_at,
        run_id=run.id,
        selected_agent=completion["selected_agent"],
        pending_approval_id=completion.get("pending_approval_id"),
    )


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_conversation_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Message]:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    messages = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    return list(messages.scalars().all())


@router.get("/agents")
async def list_agents() -> list[dict[str, str]]:
    from app.ai.agents.supervisor import AGENT_DESCRIPTIONS

    return [{"name": name, "description": description} for name, description in AGENT_DESCRIPTIONS.items()]


@router.get("/agents/runs/{run_id}/events")
async def list_agent_run_events(
    run_id: str,
    after: int = 0,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    events = await session.execute(
        select(AgentEvent)
        .where(AgentEvent.agent_run_id == run_id, AgentEvent.sequence > after)
        .order_by(AgentEvent.sequence)
    )
    return [
        {
            "event_id": event.id,
            "sequence": event.sequence,
            "type": event.event_type,
            "conversation_id": run.conversation_id,
            "run_id": run_id,
            "created_at": event.created_at,
            "data": {"agent": event.agent_name, **event.payload},
        }
        for event in events.scalars().all()
    ]


@router.post("/agents/runs/{run_id}/resume", response_model=ChatResponse)
async def resume_agent_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if run.status not in {"running", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent run is not resumable")

    conversation_result = await session.execute(
        select(Conversation).where(
            Conversation.id == run.conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    checkpoint_result = await session.execute(
        select(AgentCheckpoint).where(
            AgentCheckpoint.agent_run_id == run.id,
            AgentCheckpoint.checkpoint_key == "worker-completed",
        )
    )
    completed_checkpoint = checkpoint_result.scalar_one_or_none()
    completed_state = completed_checkpoint.state_data if completed_checkpoint is not None else None
    if completed_state is None:
        pending_checkpoint_result = await session.execute(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run.id,
                AgentCheckpoint.checkpoint_key == "approval-pending",
            )
        )
        pending_checkpoint = pending_checkpoint_result.scalar_one_or_none()
        pending_state = pending_checkpoint.state_data if pending_checkpoint is not None else None
        approved_state: WorkflowState | None = None
        if pending_state:
            approval_result = await session.execute(
                select(Approval).where(
                    Approval.agent_run_id == run.id,
                    Approval.status == "approved",
                )
            )
            approval = approval_result.scalar_one_or_none()
            if approval is not None:
                execution_result = await session.execute(
                    select(ToolExecution).where(
                        ToolExecution.agent_run_id == run.id,
                        ToolExecution.tool_name == approval.tool_name,
                        ToolExecution.status == "completed",
                    )
                )
                execution = next(
                    (
                        item
                        for item in execution_result.scalars().all()
                        if item.input_data == approval.tool_arguments and item.output_data is not None
                    ),
                    None,
                )
                if execution is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Approved tool result is unavailable",
                    )
                continuation_messages = pending_state.get("continuation_messages")
                if not isinstance(continuation_messages, list):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Approval continuation is unavailable",
                    )
                approved_state = {
                    **pending_state,
                    "messages": [
                        *continuation_messages,
                        {
                            "role": "tool",
                            "tool_call_id": approval.tool_call_id,
                            "content": json.dumps(execution.output_data, ensure_ascii=True),
                        },
                    ],
                    "step_count": pending_state.get("step_count", 0) + 1,
                }

        if approved_state is not None:
            state = approved_state
        else:
            checkpoint_result = await session.execute(
                select(AgentCheckpoint).where(
                    AgentCheckpoint.agent_run_id == run.id,
                    AgentCheckpoint.checkpoint_key == "worker-start",
                )
            )
            checkpoint = checkpoint_result.scalar_one_or_none()
            state = checkpoint.state_data if checkpoint is not None else run.state_snapshot
        if not state or not state.get("messages"):
            history_result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(MAX_CONTEXT_MESSAGES)
            )
            history = list(reversed(history_result.scalars().all()))
            last_user_message = next((message for message in reversed(history) if message.role == "user"), None)
            if last_user_message is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No user message to resume")
            model_role = "coding" if run.model_id == resolve_model("coding") else "general"
            state = {
                "run_id": run.id,
                "conversation_id": conversation.id,
                "user_id": user.id,
                "request": last_user_message.content,
                "model_role": model_role,
                "messages": [{"role": message.role, "content": message.content} for message in history],
                "step_count": 0,
            }

    run.status = "running"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="agent.status",
        payload={"status": "resuming"},
    )
    if completed_state is None:
        try:
            completed_state = await run_workflow(session=session, client=openrouter, run=run, state=state)
        except OpenRouterError as exc:
            raise HTTPException(
                status_code=provider_http_status(exc),
                detail=exc.user_message,
            ) from None

    existing_messages = await session.execute(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "assistant",
        )
    )
    already_saved = any(
        message.metadata_json and message.metadata_json.get("agent_run_id") == run.id
        for message in existing_messages.scalars().all()
    )
    now = datetime.now(timezone.utc)
    if not already_saved:
        session.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation.id,
                role="assistant",
                content=completed_state["answer"],
                metadata_json={
                    "model": completed_state["model_id"],
                    "reasoning_details": completed_state.get("reasoning_details"),
                    "usage": completed_state.get("usage"),
                    "agent": completed_state["selected_agent"],
                    "agent_run_id": run.id,
                },
                created_at=now,
            )
        )
    conversation.updated_at = now
    run.status = "completed"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="workflow.completed",
        payload={
            "status": "completed",
            "model": completed_state["model_id"],
            "selected_agent": completed_state["selected_agent"],
            "resumed": True,
        },
    )
    return ChatResponse(
        conversation_id=conversation.id,
        reply=completed_state["answer"],
        model=completed_state["model_id"],
        created_at=now,
        run_id=run.id,
        selected_agent=completed_state["selected_agent"],
    )
