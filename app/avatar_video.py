"""
InstaBio Avatar Video Pipeline
Calls Veron's SadTalker API to generate talking head videos.
Also handles TTS (text-to-speech) for the interviewer's voice.

Separate from avatar.py (which handles photo upload/status tracking).
"""

import asyncio
import json
import httpx
from typing import Optional, List, Dict
from pathlib import Path

VERON_AVATAR_API = "http://24.11.183.106:8100"
VERON_OLLAMA_API = "http://24.11.183.106:11434"
VERON_TTS_API = "http://24.11.183.106:8100"  # TTS endpoint on same service

# Default interviewer portrait
DEFAULT_PORTRAIT = "default"
PORTRAITS_DIR = Path(__file__).parent.parent / "static" / "portraits"


async def check_veron_available() -> bool:
    """Check if Veron's SadTalker API is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{VERON_AVATAR_API}/health")
            return resp.status_code == 200
    except Exception:
        return False


async def generate_tts_audio(text: str) -> Optional[bytes]:
    """
    Generate speech audio from text using Veron's TTS service.
    Returns audio bytes or None if unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{VERON_TTS_API}/tts",
                json={"text": text, "voice": "warm_female"},
            )
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"TTS generation failed: {e}")
    return None


async def generate_avatar_video(text: str, portrait_id: str = DEFAULT_PORTRAIT) -> Optional[str]:
    """
    Generate a talking head video from text.
    
    Pipeline:
    1. Generate TTS audio from text
    2. Call SadTalker on Veron to animate portrait with audio
    3. Return URL to the generated video
    
    Returns video URL or None if Veron is unavailable (caller should use fallback).
    """
    if not await check_veron_available():
        return None

    # Step 1: TTS
    audio_bytes = await generate_tts_audio(text)
    if not audio_bytes:
        return None

    # Step 2: SadTalker
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{VERON_AVATAR_API}/generate",
                files={"audio": ("question.wav", audio_bytes, "audio/wav")},
                data={"portrait_id": portrait_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("video_url")
    except Exception as e:
        print(f"Avatar video generation failed: {e}")

    return None


async def list_portraits() -> List[Dict]:
    """List available interviewer portraits."""
    portraits = [
        {
            "id": "default",
            "name": "Sarah",
            "description": "A warm, friendly interviewer",
            "image_url": "/static/portraits/default.jpg",
        }
    ]

    # Check for additional portraits on disk
    if PORTRAITS_DIR.exists():
        for f in PORTRAITS_DIR.iterdir():
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and f.stem != "default":
                portraits.append({
                    "id": f.stem,
                    "name": f.stem.replace("_", " ").title(),
                    "description": "Custom interviewer portrait",
                    "image_url": f"/static/portraits/{f.name}",
                })

    return portraits


async def get_portrait(portrait_id: str) -> Optional[Dict]:
    """Get a specific portrait by ID."""
    portraits = await list_portraits()
    for p in portraits:
        if p["id"] == portrait_id:
            return p
    return None
