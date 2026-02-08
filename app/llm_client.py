"""
InstaBio LLM Client
Connects to Ollama running on Veron 1 (5090 GPU)
"""

import asyncio
import json
import subprocess
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


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
    Uses SSH tunnel to communicate with the remote Ollama instance.
    """
    
    def __init__(
        self,
        model: str = "qwen2.5:32b",
        timeout: int = 120,
        use_mock: bool = False
    ):
        self.model = model
        self.timeout = timeout
        self.use_mock = use_mock
        self._veron_available: Optional[bool] = None
    
    async def check_availability(self) -> bool:
        """Check if Veron 1 Ollama is available."""
        if self._veron_available is not None:
            return self._veron_available
        
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
                models = [m.get('name', '') for m in data.get('models', [])]
                self._veron_available = self.model in models
                return self._veron_available
        except Exception as e:
            print(f"Veron check failed: {e}")
        
        self._veron_available = False
        return False
    
    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Generate text from the LLM.
        Falls back to mock if Veron is unavailable.
        """
        # Check if we should use mock
        if self.use_mock or not await self.check_availability():
            return await self._mock_generate(prompt, system)
        
        try:
            # Build the request
            request = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }
            
            if system:
                request["system"] = system
            
            # Escape the JSON for shell
            request_json = json.dumps(request).replace("'", "'\\''")
            
            # Execute via SSH
            cmd = f"curl -s http://localhost:11434/api/generate -d '{request_json}'"
            
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
                return LLMResponse(
                    text="",
                    model=self.model,
                    success=False,
                    error=f"SSH failed: {stderr.decode()}"
                )
            
            # Parse response
            response = json.loads(stdout.decode())
            
            return LLMResponse(
                text=response.get("response", ""),
                model=self.model,
                success=True,
                raw_response=response
            )
            
        except asyncio.TimeoutError:
            return LLMResponse(
                text="",
                model=self.model,
                success=False,
                error="Request timed out"
            )
        except Exception as e:
            return LLMResponse(
                text="",
                model=self.model,
                success=False,
                error=str(e)
            )
    
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
        if self.use_mock or not await self.check_availability():
            # Extract last user message for mock
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                ""
            )
            system = next(
                (m["content"] for m in messages if m["role"] == "system"),
                None
            )
            return await self._mock_generate(last_user, system)
        
        try:
            request = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }
            
            request_json = json.dumps(request).replace("'", "'\\''")
            cmd = f"curl -s http://localhost:11434/api/chat -d '{request_json}'"
            
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
                return LLMResponse(
                    text="",
                    model=self.model,
                    success=False,
                    error=f"SSH failed: {stderr.decode()}"
                )
            
            response = json.loads(stdout.decode())
            message = response.get("message", {})
            
            return LLMResponse(
                text=message.get("content", ""),
                model=self.model,
                success=True,
                raw_response=response
            )
            
        except asyncio.TimeoutError:
            return LLMResponse(
                text="",
                model=self.model,
                success=False,
                error="Request timed out"
            )
        except Exception as e:
            return LLMResponse(
                text="",
                model=self.model,
                success=False,
                error=str(e)
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


async def test_connection() -> bool:
    """Test the Ollama connection."""
    client = get_llm_client()
    return await client.check_availability()
