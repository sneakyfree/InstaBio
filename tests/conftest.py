"""
InstaBio Test Configuration
Sets up isolated test database and async httpx client for each test.
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pathlib import Path


@pytest_asyncio.fixture
async def client(tmp_path):
    """Create test client with an isolated temp database."""
    db_path = str(tmp_path / "test_instabio.db")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["TESTING"] = "1"

    # Force database module to re-read the env var
    from app import database as db_mod
    db_mod.DB_PATH = Path(db_path)

    # Initialize fresh schema
    await db_mod.init_db()

    # Import app AFTER setting DB path
    from app.main import app

    # Disable rate limiting for tests
    app.state.limiter.enabled = False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    # Re-enable after test
    app.state.limiter.enabled = True
    os.environ.pop("TESTING", None)


@pytest_asyncio.fixture
async def registered_user(client):
    """Register a test user and return (client, token, user_id)."""
    response = await client.post("/api/register", json={
        "first_name": "TestUser",
        "birth_year": 1950,
        "email": "testuser@example.com"
    })
    assert response.status_code == 200, f"Registration failed: {response.text}"
    data = response.json()
    return client, data["token"], data["user_id"]
