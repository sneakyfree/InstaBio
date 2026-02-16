"""
InstaBio Auth Tests
Tests token expiration, auth guards, and registration edge cases.
"""

import pytest
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_token_expires_after_configured_days(client):
    """A token older than TOKEN_EXPIRY_DAYS should return 401."""
    import os
    os.environ["TOKEN_EXPIRY_DAYS"] = "1"  # 1 day for fast test

    # Register user
    response = await client.post("/api/register", json={
        "first_name": "Expired",
        "birth_year": 1940,
        "email": "expired@example.com"
    })
    data = response.json()
    token = data["token"]

    # Manually backdate token_created_at to 2 days ago
    from app import database as db_mod
    import aiosqlite
    async with aiosqlite.connect(db_mod.DB_PATH) as db:
        two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
        await db.execute(
            "UPDATE users SET token_created_at = ? WHERE id = ?",
            (two_days_ago, data["user_id"])
        )
        await db.commit()

    # Now the token should be expired
    response = await client.get("/api/user/stats", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()

    # Cleanup
    os.environ["TOKEN_EXPIRY_DAYS"] = "90"


@pytest.mark.asyncio
async def test_fresh_token_works(client):
    """A freshly created token should authenticate successfully."""
    response = await client.post("/api/register", json={
        "first_name": "Fresh",
        "birth_year": 1955,
        "email": "fresh@example.com"
    })
    token = response.json()["token"]

    response = await client.get("/api/user/stats", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logout_invalidates_token(client):
    """After logout, the old token should no longer work."""
    # Register
    response = await client.post("/api/register", json={
        "first_name": "Logout",
        "birth_year": 1960,
        "email": "logout@example.com"
    })
    token = response.json()["token"]

    # Verify token works
    response = await client.get("/api/user/stats", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200

    # Logout
    response = await client.post("/api/logout", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200

    # Old token should fail
    response = await client.get("/api/user/stats", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 401
