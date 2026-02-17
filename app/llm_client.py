"""
InstaBio LLM Client
Connects to Ollama running on Veron 1 (5090 GPU)

Fallback chain: SSH tunnel → direct HTTP → mock
"""

import asyncio
import json
import os
import subprocess
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class Transport(Enum):
    SSH = "ssh"
    HTTP = "http"
    MOCK = "mock"


@dataclass
class LLMResponse:
    """Response from LLM"""
    text: str
    model: str
    success: bool
    error: Optional[str] = None
    raw_response: Optional[Dict] = None


class OllamaClient:
    """
    Client for Ollama running on Veron 1.
    Fallback chain: SSH tunnel → direct HTTP → mock.
    """
    
    FALLBACK_MODELS = ["qwen2.5:32b", "llama3.3:70b"]
    
    def __init__(
        self,
        model: Optional[str] = None,
        timeout: int = 120,
        use_mock: bool = False
    ):
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")
        self.timeout = timeout
        self.use_mock = use_mock
        self.ollama_base_url = os.environ.get(
            "VERON_OLLAMA_API", "http://24.11.183.106:11434"
        )
        self._transport: Optional[Transport] = None
        self._resolved_model: Optional[str] = None
    
    async def _detect_transport(self) -> Transport:
        """Detect the best available transport: SSH → HTTP → mock."""
        if self._transport is not None:
            return self._transport
        
        if self.use_mock:
            self._transport = Transport.MOCK
            self._resolved_model = "mock"
            return self._transport
        
        # Try SSH first
        try:
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "veron1-ssh",
                    "curl -s http://localhost:11434/api/tags",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=10
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0:
                data = json.loads(stdout.decode())
                available_models = [m.get('name', '') for m in data.get('models', [])]
                resolved = self._pick_model(available_models)
                if resolved:
                    self._transport = Transport.SSH
                    self._resolved_model = resolved
                    logger.info(f"LLM transport: SSH (model: {resolved})")
                    return self._transport
        except Exception as e:
            logger.debug(f"SSH transport unavailable: {e}")
        
        # Try direct HTTP
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.ollama_base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    available_models = [m.get('name', '') for m in data.get('models', [])]
                    resolved = self._pick_model(available_models)
                    if resolved:
                        self._transport = Transport.HTTP
                        self._resolved_model = resolved
                        logger.info(f"LLM transport: HTTP → {self.ollama_base_url} (model: {resolved})")
                        return self._transport
        except Exception as e:
            logger.debug(f"HTTP transport unavailable: {e}")
        
        # Fall back to mock
        self._transport = Transport.MOCK
        self._resolved_model = "mock"
        logger.warning("LLM transport: MOCK (no Ollama reachable)")
        return self._transport
    
    def _pick_model(self, available: List[str]) -> Optional[str]:
        """Pick the best available model from preferences."""
        # Check requested model first
        if self.model in available:
            return self.model
        # Try fallbacks
        for fallback in self.FALLBACK_MODELS:
            if fallback in available:
                return fallback
        # If models exist at all, use the first one
        if available:
            return available[0]
        return None
    
    async def check_availability(self) -> bool:
        """Check if any real LLM transport is available."""
        transport = await self._detect_transport()
        return transport != Transport.MOCK
    
    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate text from the LLM.
        Falls back through: SSH → HTTP → mock.
        """
        transport = await self._detect_transport()
        model = self._resolved_model
        
        if transport == Transport.MOCK:
            return await self._mock_generate(prompt, system)
        
        request = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if system:
            request["system"] = system
        
        try:
            if transport == Transport.SSH:
                return await self._ssh_request("/api/generate", request, model)
            else:
                return await self._http_request("/api/generate", request, model)
        except Exception as e:
            # On failure, try the other transport before falling to mock
            logger.warning(f"{transport.value} request failed ({e}), trying fallback…")
            self._transport = None  # reset cache to re-detect
            new_transport = await self._detect_transport()
            if new_transport != Transport.MOCK and new_transport != transport:
                try:
                    if new_transport == Transport.SSH:
                        return await self._ssh_request("/api/generate", request, model)
                    else:
                        return await self._http_request("/api/generate", request, model)
                except Exception as e2:
                    logger.warning(f"Fallback {new_transport.value} also failed: {e2}")
            
            # Last resort: mock
            return await self._mock_generate(prompt, system)
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Chat completion with message history.
        Messages format: [{"role": "user/assistant/system", "content": "..."}]
        """
        transport = await self._detect_transport()
        model = self._resolved_model
        
        if transport == Transport.MOCK:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                ""
            )
            system = next(
                (m["content"] for m in messages if m["role"] == "system"),
                None
            )
            return await self._mock_generate(last_user, system)
        
        request = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        try:
            if transport == Transport.SSH:
                result = await self._ssh_request("/api/chat", request, model)
            else:
                result = await self._http_request("/api/chat", request, model)
            
            # Chat endpoint returns message.content instead of response
            if result.success and result.raw_response:
                message = result.raw_response.get("message", {})
                result.text = message.get("content", result.text)
            return result
            
        except Exception as e:
            logger.warning(f"{transport.value} chat failed ({e}), trying fallback…")
            self._transport = None
            new_transport = await self._detect_transport()
            if new_transport != Transport.MOCK and new_transport != transport:
                try:
                    if new_transport == Transport.SSH:
                        result = await self._ssh_request("/api/chat", request, model)
                    else:
                        result = await self._http_request("/api/chat", request, model)
                    if result.success and result.raw_response:
                        message = result.raw_response.get("message", {})
                        result.text = message.get("content", result.text)
                    return result
                except Exception as e2:
                    logger.warning(f"Fallback {new_transport.value} also failed: {e2}")
            
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                ""
            )
            system_msg = next(
                (m["content"] for m in messages if m["role"] == "system"),
                None
            )
            return await self._mock_generate(last_user, system_msg)
    
    async def _ssh_request(self, endpoint: str, request: Dict, model: str) -> LLMResponse:
        """Execute Ollama request via SSH tunnel."""
        request_json = json.dumps(request).replace("'", "'\\''")
        cmd = f"curl -s http://localhost:11434{endpoint} -d '{request_json}'"
        
        proc = await asyncio.create_subprocess_exec(
            "veron1-ssh",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=self.timeout
        )
        
        if proc.returncode != 0:
            raise ConnectionError(f"SSH failed: {stderr.decode()}")
        
        response = json.loads(stdout.decode())
        return LLMResponse(
            text=response.get("response", ""),
            model=model,
            success=True,
            raw_response=response
        )
    
    async def _http_request(self, endpoint: str, request: Dict, model: str) -> LLMResponse:
        """Execute Ollama request via direct HTTP."""
        url = f"{self.ollama_base_url}{endpoint}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=request)
            
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            
            response = resp.json()
            return LLMResponse(
                text=response.get("response", ""),
                model=model,
                success=True,
                raw_response=response
            )
    
    async def _mock_generate(
        self,
        prompt: str,
        system: Optional[str] = None
    ) -> LLMResponse:
        """
        Mock generation for development/testing when Veron is unavailable.
        Returns placeholder content based on prompt hints.
        """
        await asyncio.sleep(0.5)  # Simulate delay
        
        prompt_lower = prompt.lower()
        
        # Entity extraction mock
        if "extract" in prompt_lower and ("entities" in prompt_lower or "people" in prompt_lower):
            mock_response = json.dumps({
                "people": [
                    {"name": "John", "relationship": "husband", "confidence": "exact"},
                    {"name": "Mary", "relationship": "mother", "confidence": "exact"},
                    {"name": "Robert", "relationship": "father", "confidence": "inferred"}
                ],
                "places": [
                    {"name": "Salt Lake City", "type": "city", "context": "where we moved", "confidence": "exact"},
                    {"name": "Kansas", "type": "state", "context": "hometown", "confidence": "exact"}
                ],
                "dates": [
                    {"date": "1968", "type": "year", "event": "moved to Salt Lake City", "confidence": "exact"},
                    {"date": "late 1960s", "type": "approximate", "event": "started at the factory", "confidence": "approximate"}
                ],
                "events": [
                    {"type": "move", "description": "Moved to Salt Lake City", "date": "1968", "confidence": "exact"},
                    {"type": "job", "description": "Started working at the factory", "date": "fall 1968", "confidence": "approximate"}
                ]
            }, indent=2)
        
        # Biography chapter mock
        elif "chapter" in prompt_lower or "biography" in prompt_lower or "narrative" in prompt_lower:
            mock_response = """I was born in Kansas, in a small town where everyone knew everyone. My father, Robert, worked the land like his father before him. My mother, Mary, was the heart of our home — always cooking, always singing.

In 1968, everything changed. John and I decided to move west, to Salt Lake City. The mountains there were unlike anything I'd ever seen, coming from the flatlands of Kansas. John found work at the factory that fall, and I started to build our new life, one day at a time.

Those early years were hard but good. We didn't have much, but we had each other. And every evening, when John came home, we'd sit on the porch and watch the sun set behind those magnificent mountains."""
        
        # Journal entry mock
        elif "journal" in prompt_lower or "diary" in prompt_lower:
            mock_response = """*Reconstructed from memory*

Today marks a new chapter. We've finally arrived in Salt Lake City after the long drive from Kansas. The mountains! Oh, the mountains — I've never seen anything so grand. John says we'll be happy here, and I believe him.

The apartment is small but clean. Tomorrow he starts at the factory. I'm nervous but hopeful. This is our fresh start."""
        
        # Timeline mock
        elif "timeline" in prompt_lower or "chronolog" in prompt_lower:
            mock_response = json.dumps([
                {"date": "1945", "event": "Born in Kansas", "confidence": "inferred"},
                {"date": "1963", "event": "Married John", "confidence": "approximate"},
                {"date": "1968", "event": "Moved to Salt Lake City", "confidence": "exact"},
                {"date": "Fall 1968", "event": "John started at the factory", "confidence": "exact"}
            ], indent=2)
        
        # Interview question mock
        elif "question" in prompt_lower or "interview" in prompt_lower:
            mock_response = "That's a wonderful memory. Can you tell me more about what daily life was like during that time? What did a typical day look like for you?"
        
        # Default mock
        else:
            mock_response = "This is a mock response. The actual content would be generated by the LLM based on the user's recordings and transcripts."
        
        return LLMResponse(
            text=mock_response,
            model="mock",
            success=True,
            error=None
        )


# Global client instance
_client: Optional[OllamaClient] = None


def get_llm_client(use_mock: bool = False) -> OllamaClient:
    """Get or create the global LLM client."""
    global _client
    if _client is None:
        _client = OllamaClient(use_mock=use_mock)
    return _client


async def test_connection() -> Dict[str, Any]:
    """Test the Ollama connection and report transport info."""
    client = get_llm_client()
    transport = await client._detect_transport()
    return {
        "available": transport != Transport.MOCK,
        "transport": transport.value,
        "model": client._resolved_model,
        "ollama_url": client.ollama_base_url,
    }

