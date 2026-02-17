"""
Tests for LLM client fallback chain: SSH → HTTP → mock.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json
import os

from app.llm_client import OllamaClient, Transport, LLMResponse


@pytest.fixture
def fresh_client():
    """Create a fresh OllamaClient with no cached transport."""
    return OllamaClient(model="qwen2.5:32b", use_mock=False)


@pytest.fixture
def mock_client():
    """Create an OllamaClient forced to mock mode."""
    return OllamaClient(use_mock=True)


# ---------- Transport Detection ----------

@pytest.mark.asyncio
async def test_mock_mode_skips_ssh_and_http(mock_client):
    """When use_mock=True, transport detection should immediately return MOCK."""
    transport = await mock_client._detect_transport()
    assert transport == Transport.MOCK
    assert mock_client._resolved_model == "mock"


@pytest.mark.asyncio
async def test_ssh_failure_falls_to_http(fresh_client):
    """When SSH is unavailable but HTTP works, should use HTTP transport."""
    # Patch SSH at the module level where it's called
    with patch("app.llm_client.asyncio.create_subprocess_exec",
               side_effect=FileNotFoundError("veron1-ssh not found")):
        # HTTP succeeds
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "qwen2.5:32b"}, {"name": "llama3.3:70b"}]
        }
        
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        
        with patch("app.llm_client.httpx.AsyncClient", return_value=mock_http):
            transport = await fresh_client._detect_transport()
    
    assert transport == Transport.HTTP
    assert fresh_client._resolved_model == "qwen2.5:32b"


@pytest.mark.asyncio
async def test_ssh_and_http_failure_falls_to_mock(fresh_client):
    """When both SSH and HTTP are unavailable, should fall to MOCK."""
    with patch("app.llm_client.asyncio.create_subprocess_exec",
               side_effect=FileNotFoundError("veron1-ssh not found")):
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=ConnectionError("refused"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        
        with patch("app.llm_client.httpx.AsyncClient", return_value=mock_http):
            transport = await fresh_client._detect_transport()
    
    assert transport == Transport.MOCK
    assert fresh_client._resolved_model == "mock"


# ---------- Model Selection ----------

def test_model_fallback_order(fresh_client):
    """If primary model unavailable, should pick from FALLBACK_MODELS."""
    fresh_client.model = "nonexistent-model:latest"
    result = fresh_client._pick_model(["llama3.3:70b", "other-model:7b"])
    assert result == "llama3.3:70b"


def test_model_primary_preferred(fresh_client):
    """Primary model should be selected first if available."""
    result = fresh_client._pick_model(["llama3.3:70b", "qwen2.5:32b"])
    assert result == "qwen2.5:32b"


def test_model_no_match_picks_first(fresh_client):
    """If no known model matches, should pick the first available model."""
    fresh_client.model = "nonexistent:latest"
    result = fresh_client._pick_model(["custom-model:13b"])
    assert result == "custom-model:13b"


def test_model_empty_returns_none(fresh_client):
    """If no models available at all, should return None."""
    result = fresh_client._pick_model([])
    assert result is None


# ---------- Generate (Mock Mode) ----------

@pytest.mark.asyncio
async def test_generate_mock_returns_success(mock_client):
    """Mock generate should always return success."""
    result = await mock_client.generate("Tell me about Kansas.")
    
    assert isinstance(result, LLMResponse)
    assert result.success is True
    assert result.model == "mock"
    assert len(result.text) > 0


@pytest.mark.asyncio
async def test_generate_mock_entity_extraction(mock_client):
    """Mock should return JSON for entity extraction prompts."""
    result = await mock_client.generate("Extract entities and people from this transcript.")
    
    assert result.success is True
    data = json.loads(result.text)
    assert "people" in data
    assert "places" in data


@pytest.mark.asyncio
async def test_generate_mock_biography(mock_client):
    """Mock should return narrative text for biography prompts."""
    result = await mock_client.generate("Write a biography chapter about the family.")
    
    assert result.success is True
    assert len(result.text) > 20


@pytest.mark.asyncio
async def test_generate_mock_interview(mock_client):
    """Mock should return a follow-up question for interview prompts."""
    result = await mock_client.generate("Generate the next interview question.")
    
    assert result.success is True
    assert "?" in result.text


# ---------- Chat (Mock Mode) ----------

@pytest.mark.asyncio
async def test_chat_mock_returns_success(mock_client):
    """Mock chat should always return success."""
    messages = [
        {"role": "system", "content": "You are a biographer."},
        {"role": "user", "content": "Tell me about the 1960s."}
    ]
    result = await mock_client.chat(messages)
    
    assert isinstance(result, LLMResponse)
    assert result.success is True
    assert result.model == "mock"
    assert len(result.text) > 0


# ---------- Environment Variable Respect ----------

def test_env_var_ollama_url():
    """Client should respect VERON_OLLAMA_API env var."""
    with patch.dict(os.environ, {"VERON_OLLAMA_API": "http://custom-host:9999"}):
        client = OllamaClient()
        assert client.ollama_base_url == "http://custom-host:9999"


def test_env_var_model():
    """Client should respect OLLAMA_MODEL env var."""
    with patch.dict(os.environ, {"OLLAMA_MODEL": "custom-model:latest"}):
        client = OllamaClient()
        assert client.model == "custom-model:latest"


# ---------- Check Availability ----------

@pytest.mark.asyncio
async def test_check_availability_true_when_http(fresh_client):
    """check_availability should return True when HTTP transport works."""
    fresh_client._transport = Transport.HTTP
    fresh_client._resolved_model = "qwen2.5:32b"
    
    assert await fresh_client.check_availability() is True


@pytest.mark.asyncio
async def test_check_availability_false_when_mock(mock_client):
    """check_availability should return False when in mock mode."""
    assert await mock_client.check_availability() is False


# ---------- Generate Fallback Behavior ----------

@pytest.mark.asyncio
async def test_generate_falls_back_to_mock_on_total_failure(fresh_client):
    """If both SSH and HTTP fail during generate, should return mock response."""
    # Force detection to think HTTP is available
    fresh_client._transport = Transport.HTTP
    fresh_client._resolved_model = "qwen2.5:32b"
    
    # But HTTP request itself fails
    with patch("app.llm_client.httpx.AsyncClient") as mock_httpx:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("connection lost"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_http
        
        # Also SSH fails on re-detect
        with patch("app.llm_client.asyncio.create_subprocess_exec",
                   side_effect=FileNotFoundError("no ssh")):
            result = await fresh_client.generate("Tell me about Kansas.")
    
    assert result.success is True
    assert result.model == "mock"
