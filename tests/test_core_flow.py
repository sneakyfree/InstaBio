"""
InstaBio Core Flow Tests
Tests the critical path: register → auth → session → upload → list.
"""

import pytest


@pytest.mark.asyncio
async def test_health(client):
    """GET /api/health should return 200 with status healthy."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_register_new_user(client):
    """POST /api/register with valid data should create user and return token."""
    response = await client.post("/api/register", json={
        "first_name": "Alice",
        "birth_year": 1945,
        "email": "alice@example.com"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["token"]  # non-empty
    assert data["user_id"] > 0
    assert data["first_name"] == "Alice"


@pytest.mark.asyncio
async def test_register_returns_existing_user(client):
    """Registering same email twice should return the same user."""
    payload = {
        "first_name": "Bob",
        "birth_year": 1960,
        "email": "bob@example.com"
    }
    r1 = await client.post("/api/register", json=payload)
    r2 = await client.post("/api/register", json=payload)

    d1 = r1.json()
    d2 = r2.json()
    assert d1["user_id"] == d2["user_id"]
    assert d2["message"] == "Welcome back! We found your account."


@pytest.mark.asyncio
async def test_auth_required_no_header(client):
    """GET /api/user/stats without Authorization header should return 401."""
    response = await client.get("/api/user/stats")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_required_bad_token(client):
    """GET /api/user/stats with invalid token should return 401."""
    response = await client.get("/api/user/stats", headers={
        "Authorization": "Bearer totally_invalid_token_12345"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_user_stats(registered_user):
    """Authenticated user should get their stats (initially zeroed)."""
    client, token, user_id = registered_user
    response = await client.get("/api/user/stats", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["total_sessions"] == 0
    assert data["total_words"] == 0


@pytest.mark.asyncio
async def test_start_session(registered_user):
    """Starting a recording session should return a session UUID."""
    client, token, _ = registered_user
    response = await client.post("/api/session/start", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["session_uuid"]  # non-empty UUID


@pytest.mark.asyncio
async def test_get_sessions_after_start(registered_user):
    """After starting a session, GET /api/sessions should list it."""
    client, token, _ = registered_user

    # Start a session
    start_resp = await client.post("/api/session/start", headers={
        "Authorization": f"Bearer {token}"
    })
    session_uuid = start_resp.json()["session_uuid"]

    # List sessions
    response = await client.get("/api/sessions", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["sessions"][0]["session_uuid"] == session_uuid


@pytest.mark.asyncio
async def test_get_transcripts_empty(registered_user):
    """Initially a user should have no transcripts."""
    client, token, _ = registered_user
    response = await client.get("/api/transcripts", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 0
    assert data["transcripts"] == []
