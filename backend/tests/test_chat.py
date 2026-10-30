import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.ai.openrouter import OpenRouterClient
from app.api.routes import chat as chat_route
from app.config import settings
from app.database.models import AgentCheckpoint, AgentEvent, AgentRun, Message
from app.main import app


@pytest.mark.asyncio
async def test_chat_persists_conversation_and_replays_reasoning_details(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    seen_requests = []
    reasoning_details = [{"type": "opaque", "payload": "preserve exactly"}]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_requests.append(body)
        if len(seen_requests) == 2:
            previous_assistant = next(message for message in body["messages"] if message["role"] == "assistant")
            assert previous_assistant["reasoning_details"] == reasoning_details
        text = f"answer-{len(seen_requests)}"
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": text,
                            "reasoning_details": reasoning_details,
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "chat-user@example.com", "password": "a-strong-password-123", "name": "Chat User"},
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "chat-user@example.com", "password": "a-strong-password-123"},
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/v1/chat", headers=headers, json={"message": "Hello"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["reply"] == "answer-1"
    UUID(first_body["conversation_id"])

    second = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Continue", "conversation_id": first_body["conversation_id"], "model_role": "coding"},
    )
    assert second.status_code == 200
    assert second.json()["reply"] == "answer-2"
    assert seen_requests[1]["model"] == settings.coding_model

    conversations = await client.get("/api/v1/conversations", headers=headers)
    assert conversations.status_code == 200
    assert len(conversations.json()) == 1

    messages = await client.get(
        f"/api/v1/conversations/{first_body['conversation_id']}/messages",
        headers=headers,
    )
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()] == ["user", "assistant", "user", "assistant"]
    assert registration.status_code == 201
    run_id = second.json()["run_id"]
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "completed"
        assert run.selected_agent == "assistant"
        events = await session.execute(
            select(AgentEvent).where(AgentEvent.agent_run_id == run_id).order_by(AgentEvent.sequence)
        )
        event_types = [event.event_type for event in events.scalars().all()]
        assert event_types == [
            "agent.started",
            "agent.status",
            "agent.started",
            "agent.completed",
            "workflow.completed",
        ]
        checkpoints = await session.execute(
            select(AgentCheckpoint).where(AgentCheckpoint.agent_run_id == run_id)
        )
        assert {checkpoint.checkpoint_key for checkpoint in checkpoints.scalars().all()} == {
            "supervisor-routed",
            "worker-start",
            "worker-completed",
        }


@pytest.mark.asyncio
async def test_chat_conversation_isolation(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "private reply"}}]})

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )

    async def create_user(email: str) -> str:
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "a-strong-password-123", "name": "User"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "a-strong-password-123"},
        )
        return login.json()["access_token"]

    owner_token = await create_user("owner@example.com")
    stranger_token = await create_user("stranger@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"message": "Secret"},
    )
    conversation_id = response.json()["conversation_id"]
    outsider_headers = {"Authorization": f"Bearer {stranger_token}"}

    assert (
        await client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=outsider_headers,
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/chat",
            headers=outsider_headers,
            json={"message": "Try to access", "conversation_id": conversation_id},
        )
    ).status_code == 404
    outsider_conversations = await client.get("/api/v1/conversations", headers=outsider_headers)
    assert outsider_conversations.json() == []


@pytest.mark.asyncio
async def test_failed_agent_run_resumes_from_mysql_checkpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"model": settings.primary_model, "choices": [{"message": {"content": "Recovered answer"}}]},
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    await client.post(
        "/api/v1/auth/register",
        json={"email": "resume-user@example.com", "password": "a-strong-password-123", "name": "Resume User"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "resume-user@example.com", "password": "a-strong-password-123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    failed = await client.post("/api/v1/chat", headers=headers, json={"message": "Help me debug this code"})
    assert failed.status_code == 502

    async with app.state.test_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.status == "failed"))
        assert run is not None
        run_id = run.id
        assert run.selected_agent == "developer"
        checkpoint = await session.scalar(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run_id,
                AgentCheckpoint.checkpoint_key == "worker-start",
            )
        )
        assert checkpoint is not None

    recovered = await client.post(f"/api/v1/agents/runs/{run_id}/resume", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["reply"] == "Recovered answer"
    assert recovered.json()["selected_agent"] == "developer"
    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "completed"
        saved = await session.execute(
            select(Message).where(
                Message.conversation_id == run.conversation_id,
                Message.role == "assistant",
            )
        )
        assistant_messages = [
            message for message in saved.scalars().all()
            if message.metadata_json and message.metadata_json.get("agent_run_id") == run_id
        ]
        assert len(assistant_messages) == 1


def test_supervisor_routes_specialist_intents():
    from app.ai.agents.supervisor import select_agent

    assert select_agent("Debug this Python function") == "developer"
    assert select_agent("Help me prioritize my tasks") == "productivity"
    assert select_agent("Research and compare recent sources") == "researcher"
    assert select_agent("Summarize this PDF document") == "document"
    assert select_agent("Tell me a fun fact") == "assistant"
