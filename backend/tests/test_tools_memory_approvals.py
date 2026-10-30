import json
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.ai.openrouter import OpenRouterClient
from app.api.routes import approvals as approvals_route
from app.api.routes import chat as chat_route
from app.config import settings
from app.database.models import AgentEvent, AgentRun, Approval, Memory, Message, Task
from app.main import app
from app.tools.registry import _safe_arithmetic


async def _auth_headers(client, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-strong-password-123", "name": "Test User"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "a-strong-password-123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_task_creation_tool_waits_for_approval_and_resumes(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content)
        calls += 1
        if calls == 1:
            assert body["tools"]
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call-create-task",
                                "type": "function",
                                "function": {
                                    "name": "create_task",
                                    "arguments": json.dumps({"title": "Review project plan", "priority": "high"}),
                                },
                            }],
                        },
                    }],
                },
            )
        assert body["messages"][-1]["role"] == "tool"
        assert not body.get("tools")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Task created."}}]},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(chat_route, "openrouter", OpenRouterClient(transport=transport))
    monkeypatch.setattr(approvals_route, "openrouter", OpenRouterClient(transport=transport))
    headers = await _auth_headers(client, "approval-user@example.com")

    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Please create a task to review the project plan"},
    )
    assert response.status_code == 200
    pending = response.json()
    assert pending["pending_approval_id"], pending
    run_id = pending["run_id"]

    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "waiting_approval"
        assert await session.scalar(select(Task.id)) is None

    approval_list = await client.get("/api/v1/approvals", headers=headers)
    assert approval_list.status_code == 200
    assert len(approval_list.json()) == 1
    assert approval_list.json()[0]["tool_arguments"]["title"] == "Review project plan"

    approved = await client.post(
        f"/api/v1/approvals/{pending['pending_approval_id']}/decision",
        headers=headers,
        json={"approve": True, "note": "Go ahead"},
    )
    assert approved.status_code == 200
    assert approved.json()["reply"] == "Task created."
    assert approved.json()["pending_approval_id"] is None

    async with app.state.test_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        approval = await session.get(Approval, pending["pending_approval_id"])
        task = await session.scalar(select(Task).where(Task.user_id == approval.user_id))
        events = await session.execute(
            select(AgentEvent.event_type)
            .where(AgentEvent.agent_run_id == run_id)
            .order_by(AgentEvent.sequence)
        )
        assert run.status == "completed"
        assert approval.status == "approved"
        assert task is not None and task.title == "Review project plan"
        assert "approval.approved" in list(events.scalars().all())

    duplicate = await client.post(
        f"/api/v1/approvals/{pending['pending_approval_id']}/decision",
        headers=headers,
        json={"approve": True},
    )
    assert duplicate.status_code == 409
    assert calls == 2


@pytest.mark.asyncio
async def test_rejecting_approval_does_not_create_task(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "call-reject-task",
                            "type": "function",
                            "function": {
                                "name": "create_task",
                                "arguments": '{"title":"Do not create"}',
                            },
                        }],
                    },
                }],
            },
        )

    monkeypatch.setattr(chat_route, "openrouter", OpenRouterClient(transport=httpx.MockTransport(handler)))
    headers = await _auth_headers(client, "reject-user@example.com")
    response = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Create a task to do this"},
    )
    pending_id = response.json()["pending_approval_id"]

    rejected = await client.post(
        f"/api/v1/approvals/{pending_id}/decision",
        headers=headers,
        json={"approve": False},
    )
    assert rejected.status_code == 200
    assert "ditolak" in rejected.json()["reply"]
    async with app.state.test_session_factory() as session:
        assert await session.scalar(select(Task.id)) is None
        approval = await session.get(Approval, pending_id)
        assert approval.status == "rejected"


@pytest.mark.asyncio
async def test_approved_task_is_not_recreated_when_workflow_resumes(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "content": None,
                            "tool_calls": [{
                                "id": "call-recover-task",
                                "type": "function",
                                "function": {
                                    "name": "create_task",
                                    "arguments": '{"title":"Keep one task"}',
                                },
                            }],
                        },
                    }],
                },
            )
        if calls == 2:
            return httpx.Response(503)
        body = json.loads(request.content)
        assert body["messages"][-1]["role"] == "tool"
        assert body["messages"][-1]["tool_call_id"] == "call-recover-task"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Recovered after approval."}}]},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(chat_route, "openrouter", OpenRouterClient(transport=transport))
    monkeypatch.setattr(approvals_route, "openrouter", OpenRouterClient(transport=transport))
    headers = await _auth_headers(client, "approval-recovery@example.com")
    pending = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Create a task to keep one task"},
    )
    pending_data = pending.json()

    failed_continuation = await client.post(
        f"/api/v1/approvals/{pending_data['pending_approval_id']}/decision",
        headers=headers,
        json={"approve": True},
    )
    assert failed_continuation.status_code == 502

    recovered = await client.post(
        f"/api/v1/agents/runs/{pending_data['run_id']}/resume",
        headers=headers,
    )
    assert recovered.status_code == 200
    assert recovered.json()["reply"] == "Recovered after approval."
    async with app.state.test_session_factory() as session:
        tasks = await session.scalars(select(Task))
        assert len(tasks.all()) == 1
        run = await session.get(AgentRun, pending_data["run_id"])
        approval = await session.get(Approval, pending_data["pending_approval_id"])
        assert run.status == "completed"
        assert approval.status == "approved"
    assert calls == 3


@pytest.mark.asyncio
async def test_memory_is_user_scoped_retrieved_and_rejects_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "I will remember."}}]},
        )

    monkeypatch.setattr(chat_route, "openrouter", OpenRouterClient(transport=httpx.MockTransport(handler)))
    owner_headers = await _auth_headers(client, "memory-owner@example.com")
    other_headers = await _auth_headers(client, "memory-other@example.com")
    saved = await client.post(
        "/api/v1/memory",
        headers=owner_headers,
        json={"memory_type": "preference", "content": "Prefers concise Python examples"},
    )
    assert saved.status_code == 201
    memory_id = saved.json()["id"]

    denied = await client.post(
        "/api/v1/memory",
        headers=owner_headers,
        json={"memory_type": "fact", "content": "api_key: this-should-not-be-saved"},
    )
    assert denied.status_code == 422
    other_list = await client.get("/api/v1/memory", headers=other_headers)
    assert other_list.status_code == 200 and other_list.json() == []
    assert (
        await client.patch(
            f"/api/v1/memory/{memory_id}",
            headers=other_headers,
            json={"content": "stolen"},
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/memory/{memory_id}",
            headers=owner_headers,
            json={"content": None},
        )
    ).status_code == 422

    chat = await client.post(
        "/api/v1/chat",
        headers=owner_headers,
        json={"message": "Can you show Python examples?"},
    )
    assert chat.status_code == 200
    system_prompt = seen_requests[0]["messages"][0]["content"]
    assert "Prefers concise Python examples" in system_prompt

    removed = await client.delete(f"/api/v1/memory/{memory_id}", headers=owner_headers)
    assert removed.status_code == 204
    async with app.state.test_session_factory() as session:
        assert await session.scalar(select(Memory.id)) is None


@pytest.mark.asyncio
async def test_tasks_are_scoped_to_authenticated_user(client):
    owner_headers = await _auth_headers(client, "task-owner@example.com")
    other_headers = await _auth_headers(client, "task-other@example.com")
    created = await client.post(
        "/api/v1/tasks",
        headers=owner_headers,
        json={"title": "Owner task"},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert (await client.get("/api/v1/tasks", headers=other_headers)).json() == []
    assert (
        await client.patch(
            f"/api/v1/tasks/{task_id}",
            headers=other_headers,
            json={"status": "completed"},
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/tasks/{task_id}",
            headers=owner_headers,
            json={"status": None},
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_websocket_authenticates_ownership_and_replays_event_cursors(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "WebSocket test reply"}}]},
        )

    monkeypatch.setattr(chat_route, "openrouter", OpenRouterClient(transport=httpx.MockTransport(handler)))
    owner_headers = await _auth_headers(client, "socket-owner@example.com")
    other_headers = await _auth_headers(client, "socket-other@example.com")
    token = owner_headers["Authorization"].removeprefix("Bearer ")
    chat = await client.post(
        "/api/v1/chat",
        headers=owner_headers,
        json={"message": "Test websocket replay"},
    )
    conversation_id = chat.json()["conversation_id"]
    path = f"/ws/chat/{conversation_id}"
    auth_protocols = ["aether", f"aether.bearer.{token}"]

    with TestClient(app) as sync_client:
        with sync_client.websocket_connect(path, subprotocols=["aether"]) as socket:
            with pytest.raises(WebSocketDisconnect) as missing_auth:
                socket.receive_json()
            assert missing_auth.value.code == 4401

        with sync_client.websocket_connect(
            path,
            subprotocols=[
                "aether",
                f"aether.bearer.{other_headers['Authorization'].removeprefix('Bearer ')}",
            ],
        ) as socket:
            with pytest.raises(WebSocketDisconnect) as not_owner:
                socket.receive_json()
            assert not_owner.value.code == 4404

        with sync_client.websocket_connect(path, subprotocols=auth_protocols) as socket:
            first = socket.receive_json()
            assert first["type"] == "agent.started"
            assert first["conversation_id"] == conversation_id
            cursor = json.dumps({first["run_id"]: first["sequence"]})

        replay_path = f"{path}?{urlencode({'after': cursor})}"
        with sync_client.websocket_connect(replay_path, subprotocols=auth_protocols) as socket:
            next_event = socket.receive_json()
            assert next_event["run_id"] == first["run_id"]
            assert next_event["sequence"] > first["sequence"]
            for _ in range(3):
                socket.receive_json()

            next_chat = sync_client.post(
                "/api/v1/chat",
                headers=owner_headers,
                json={
                    "message": "Continue websocket polling test",
                    "conversation_id": conversation_id,
                },
            )
            assert next_chat.status_code == 200
            live_event = socket.receive_json()
            assert live_event["type"] == "agent.started"
            assert live_event["run_id"] == next_chat.json()["run_id"]


def test_calculator_rejects_unsafe_and_invalid_arithmetic():
    assert _safe_arithmetic("2 + 3 * 4") == 14
    with pytest.raises(ValueError):
        _safe_arithmetic("1 / 0")
    with pytest.raises(ValueError):
        _safe_arithmetic("__import__('os').system('whoami')")
