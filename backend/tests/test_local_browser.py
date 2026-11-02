import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.api.routes import browser as browser_route
from app.browser.manager import BrowserPolicyError, LocalBrowserManager
from app.config import settings
from app.main import app
from app.tools.registry import tool_definitions_for


async def _auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-strong-password-123", "name": "Test User"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "a-strong-password-123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_browser_policy_requires_exact_https_host_and_default_port(monkeypatch):
    monkeypatch.setattr(settings, "browser_allowed_hosts", "web.whatsapp.com,youtube.com")
    manager = LocalBrowserManager()
    assert manager.validate_url("https://web.whatsapp.com/") == "https://web.whatsapp.com/"
    for url in (
        "http://web.whatsapp.com/",
        "https://sub.web.whatsapp.com/",
        "https://web.whatsapp.com:444/",
        "https://user@web.whatsapp.com/",
        "https://127.0.0.1/",
        "file:///C:/Users/",
    ):
        with pytest.raises(BrowserPolicyError):
            manager.validate_url(url)


def test_browser_agent_tools_are_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "browser_enabled", False)
    monkeypatch.setattr(settings, "browser_share_page_content_with_model", True)
    names = {item["function"]["name"] for item in tool_definitions_for("assistant")}
    assert "browser_open" not in names
    assert "browser_read" not in names

    monkeypatch.setattr(settings, "browser_enabled", True)
    monkeypatch.setattr(settings, "browser_share_page_content_with_model", False)
    names = {item["function"]["name"] for item in tool_definitions_for("assistant")}
    assert "browser_open" in names
    assert "browser_read" not in names

    monkeypatch.setattr(settings, "browser_share_page_content_with_model", True)
    names = {item["function"]["name"] for item in tool_definitions_for("assistant")}
    assert "browser_read" in names


@pytest.mark.asyncio
async def test_browser_endpoints_are_loopback_only(client):
    headers = await _auth_headers(client, "browser-loopback@example.com")
    transport = ASGITransport(app=app, client=("192.0.2.10", 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as remote_client:
        response = await remote_client.get("/api/v1/browser/status", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_browser_open_endpoint_uses_authenticated_local_session(client, monkeypatch):
    monkeypatch.setattr(settings, "browser_enabled", True)
    headers = await _auth_headers(client, "browser-open@example.com")

    class FakeBrowserManager:
        enabled = True

        async def open(self, url: str) -> dict[str, str]:
            return {"url": url, "title": "WhatsApp"}

    monkeypatch.setattr(browser_route, "get_browser_manager", lambda: FakeBrowserManager())
    response = await client.post(
        "/api/v1/browser/open",
        headers=headers,
        json={"url": "https://web.whatsapp.com"},
    )
    assert response.status_code == 200
    assert response.json() == {"url": "https://web.whatsapp.com", "title": "WhatsApp"}


@pytest.mark.asyncio
async def test_loopback_dependency_rejects_non_loopback_request():
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("203.0.113.1", 80)})
    with pytest.raises(HTTPException) as error:
        await browser_route.require_loopback(request)
    assert error.value.status_code == 403
