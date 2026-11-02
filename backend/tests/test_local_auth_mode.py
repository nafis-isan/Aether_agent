import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.openrouter import OpenRouterClient
from app.api.routes import chat as chat_route
from app.config import settings
from app.database.models import AgentEvent, AgentRun, Conversation, User
from app.main import app


@pytest.mark.asyncio
async def test_local_mode_uses_single_local_profile_without_login(client, monkeypatch):
    monkeypatch.setattr(settings, "local_auth_mode", True)

    mode = await client.get("/api/v1/auth/mode")
    assert mode.status_code == 200
    assert mode.json() == {"local_auth": True}

    first_profile = await client.get("/api/v1/auth/me")
    second_profile = await client.get("/api/v1/auth/me")
    assert first_profile.status_code == 200
    assert first_profile.json()["id"] == second_profile.json()["id"]
    assert first_profile.json()["email"] == "local-user@example.com"

    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "unused@example.com", "password": "a-strong-password-123", "name": "Unused"},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "local-user@example.com", "password": "not-used"},
        )
    ).status_code == 404

    async with app.state.test_session_factory() as session:
        local_users = await session.scalars(
            select(User).where(User.email == "local-user@example.com")
        )
        assert len(local_users.all()) == 1


@pytest.mark.asyncio
async def test_local_mode_denies_non_loopback_clients_and_untrusted_origins(client, monkeypatch):
    monkeypatch.setattr(settings, "local_auth_mode", True)

    remote_transport = httpx.ASGITransport(app=app, client=("192.0.2.10", 12345))
    async with httpx.AsyncClient(transport=remote_transport, base_url="http://localhost") as remote_client:
        remote_response = await remote_client.get("/health")
    assert remote_response.status_code == 403

    untrusted_origin = await client.get(
        "/api/v1/auth/mode",
        headers={"Origin": "https://untrusted.example"},
    )
    assert untrusted_origin.status_code == 403

    local_origin = await client.get(
        "/api/v1/auth/mode",
        headers={"Origin": "http://localhost:3000"},
    )
    assert local_origin.status_code == 200


@pytest.mark.asyncio
async def test_local_mode_websocket_uses_local_profile(client, monkeypatch):
    monkeypatch.setattr(settings, "local_auth_mode", True)
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_retries", 0)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Local reply"}}]},
        )

    monkeypatch.setattr(
        chat_route,
        "openrouter",
        OpenRouterClient(transport=httpx.MockTransport(handler)),
    )
    chat = await client.post("/api/v1/chat", json={"message": "Start local chat"})
    assert chat.status_code == 200
    conversation_id = chat.json()["conversation_id"]
    run_id = chat.json()["run_id"]

    async def loopback_test_app(scope, receive, send):
        test_scope = dict(scope)
        test_scope["client"] = ("127.0.0.1", 8765)
        await app(test_scope, receive, send)

    with TestClient(loopback_test_app) as local_client:
        with local_client.websocket_connect(
            f"/ws/chat/{conversation_id}",
            subprotocols=["aether", "aether.local"],
        ) as socket:
            event = socket.receive_json()
            assert event["type"] == "agent.started"
            assert event["run_id"] == run_id

    async with app.state.test_session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        run = await session.get(AgentRun, run_id)
        event = await session.scalar(
            select(AgentEvent).where(AgentEvent.agent_run_id == run_id)
        )
        assert conversation is not None
        assert run.user_id == conversation.user_id
        assert event is not None
