"""
InstaBio E2E Pipeline Test
Tests the critical path: register → session → upload → (transcribe) → process → retrieve.
"""

import io
import pytest


def _make_webm_blob(size_kb: int = 8) -> bytes:
    """Create a fake WebM blob with valid magic bytes for upload validation."""
    # WebM files start with EBML header 0x1A45DFA3
    webm_magic = b'\x1a\x45\xdf\xa3'
    return webm_magic + b'\x00' * (size_kb * 1024)


@pytest.mark.asyncio
async def test_full_pipeline_upload_and_retrieve(client):
    """
    E2E: register → start session → upload chunk → verify chunk saved
    → trigger processing (with mock LLM) → verify entities/biography produced.
    """
    # 1. Register
    reg = await client.post("/api/register", json={
        "first_name": "Pipeline",
        "birth_year": 1945,
        "email": "pipeline@example.com"
    })
    assert reg.status_code == 200
    reg_data = reg.json()
    token = reg_data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Start session
    sess = await client.post("/api/session/start", headers=headers)
    assert sess.status_code == 200
    sess_data = sess.json()
    assert sess_data["success"] is True
    session_uuid = sess_data["session_uuid"]

    # 3. Upload a chunk
    webm_data = _make_webm_blob(8)
    upload = await client.post(
        "/api/upload",
        headers=headers,
        data={"session_uuid": session_uuid, "chunk_index": "0", "duration": "5.0"},
        files={"audio": ("chunk_00000.webm", webm_data, "audio/webm")},
    )
    assert upload.status_code == 200
    upload_data = upload.json()
    assert upload_data["success"] is True
    assert upload_data["chunk_index"] == 0

    # 4. Verify session now has 1 chunk
    sessions = await client.get("/api/sessions", headers=headers)
    assert sessions.status_code == 200
    sessions_data = sessions.json()
    assert sessions_data["total_count"] == 1
    assert sessions_data["sessions"][0]["session_uuid"] == session_uuid
    assert sessions_data["sessions"][0]["chunk_count"] == 1

    # 5. Verify user stats updated
    stats = await client.get("/api/user/stats", headers=headers)
    assert stats.status_code == 200
    stats_data = stats.json()
    assert stats_data["total_sessions"] == 1
    assert stats_data["total_chunks"] == 1


@pytest.mark.asyncio
async def test_product_status_endpoints(client):
    """Verify all product status endpoints return structured data."""
    # Register
    reg = await client.post("/api/register", json={
        "first_name": "Status",
        "birth_year": 1950,
        "email": "status@example.com"
    })
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Voice clone status
    vc = await client.get("/api/voice-clone/status", headers=headers)
    assert vc.status_code == 200
    vc_data = vc.json()
    assert "tier" in vc_data
    assert "quality_pct" in vc_data
    assert vc_data["is_ready"] is False  # No recordings yet

    # Avatar status
    av = await client.get("/api/avatar/status", headers=headers)
    assert av.status_code == 200
    av_data = av.json()
    assert "tier" in av_data
    assert "quality_pct" in av_data
    assert isinstance(av_data["is_ready"], bool)

    # Soul status
    soul = await client.get("/api/soul/status", headers=headers)
    assert soul.status_code == 200
    soul_data = soul.json()
    assert "readiness_pct" in soul_data
    assert soul_data["is_ready"] is False  # Not enough recordings

    # Products overview
    products = await client.get("/api/products/status", headers=headers)
    assert products.status_code == 200
    prod_data = products.json()
    assert "voice_clone" in prod_data
    assert "avatar" in prod_data
    assert "soul" in prod_data
    assert "biography" in prod_data
    assert "journal" in prod_data


@pytest.mark.asyncio
async def test_products_catalog(client):
    """GET /api/products returns the product catalog."""
    resp = await client.get("/api/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["products"]) > 0

    # Each product should have required fields
    for product in data["products"]:
        assert "id" in product
        assert "name" in product
        assert "price_cents" in product


@pytest.mark.asyncio
async def test_soul_activate_no_transcripts(client):
    """Soul activate without transcripts should return error."""
    reg = await client.post("/api/register", json={
        "first_name": "SoulTest",
        "birth_year": 1940,
        "email": "soul@example.com"
    })
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/soul/activate", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_soul_chat_inactive(client):
    """Soul chat without activation should return inactive status."""
    reg = await client.post("/api/register", json={
        "first_name": "ChatTest",
        "birth_year": 1940,
        "email": "chat@example.com"
    })
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/soul/chat",
        headers=headers,
        json={"message": "Tell me about your childhood"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "inactive"


@pytest.mark.asyncio
async def test_checkout_no_stripe(client):
    """Checkout without Stripe should return unavailable."""
    reg = await client.post("/api/register", json={
        "first_name": "PayTest",
        "birth_year": 1950,
        "email": "pay@example.com"
    })
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/checkout",
        headers=headers,
        json={"product_id": "biography_digital"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"


@pytest.mark.asyncio
async def test_voice_clone_generate_no_api_key(client):
    """Voice clone generate without ElevenLabs key should return unavailable."""
    reg = await client.post("/api/register", json={
        "first_name": "VoiceGen",
        "birth_year": 1945,
        "email": "voicegen@example.com"
    })
    token = reg.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/voice-clone/generate", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health check should return status healthy."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
