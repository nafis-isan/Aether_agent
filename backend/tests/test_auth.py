import pytest


@pytest.mark.asyncio
async def test_register_login_and_current_user(client):
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "User@Example.com", "password": "a-strong-password-123", "name": "Aether User"},
    )
    assert registration.status_code == 201
    assert registration.json()["email"] == "user@example.com"
    assert "password_hash" not in registration.json()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "a-strong-password-123"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    profile = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == "user@example.com"
    assert "password_hash" not in profile.json()


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected_case_insensitively(client):
    payload = {"email": "User@Example.com", "password": "a-strong-password-123", "name": "User"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    payload["email"] = "user@example.com"
    duplicate = await client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_login_rejects_invalid_password_and_me_requires_auth(client):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "a-strong-password-123", "name": "User"},
    )
    invalid_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    assert invalid_login.status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401
