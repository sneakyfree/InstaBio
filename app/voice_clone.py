"""
InstaBio Voice Clone Module
Tracks progress toward voice clone quality based on recording hours.
Integrates with ElevenLabs API for voice cloning and synthesis.

Voice Clone Tiers:
- 0-1 hours: Not enough data yet (0%)
- 1-2 hours: Tier 1 — Basic clone, recognizable (25%)
- 2-5 hours: Tier 1+ — Improving (40%)
- 5-10 hours: Tier 2 — Good clone, natural (60%)
- 10-20 hours: Tier 2+ — Very good (80%)
- 20-50 hours: Tier 3 — Premium, emotional range (90%)
- 50+ hours: Tier 4 — Ultra, indistinguishable (99%)
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ElevenLabs configuration
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

# Tier thresholds in hours
TIER_THRESHOLDS = [
    (0, 1, 0, "Not enough data", "Keep recording! You need at least 1 hour for a basic voice clone."),
    (1, 2, 1, "Tier 1 — Basic Clone", "Your voice is recognizable! More hours = more natural."),
    (2, 5, 1.5, "Tier 1+ — Improving", "Getting better! Your accent and rhythm are coming through."),
    (5, 10, 2, "Tier 2 — Good Clone", "Nice! Your clone sounds natural and captures your speaking style."),
    (10, 20, 2.5, "Tier 2+ — Very Good", "Impressive! Your clone captures subtle vocal nuances."),
    (20, 50, 3, "Tier 3 — Premium", "Premium quality! Emotional range and verbal habits included."),
    (50, float('inf'), 4, "Tier 4 — Ultra", "Legendary! Your voice clone is virtually indistinguishable."),
]

# Quality percentages by tier
TIER_QUALITY = {
    0: 0,      # Not enough data
    1: 25,     # Basic
    1.5: 40,   # Improving
    2: 60,     # Good
    2.5: 80,   # Very good
    3: 90,     # Premium
    4: 99,     # Ultra
}

# Encouraging messages based on progress
ENCOURAGING_MESSAGES = [
    "Every story you tell makes your voice clone more authentic!",
    "Your grandchildren will treasure hearing your voice forever.",
    "You're building something that will last generations.",
    "Your unique way of speaking is being captured with every session.",
    "The more you record, the more 'you' your voice clone becomes!",
    "Family members will be amazed at how natural you sound.",
    "Your stories are becoming your legacy.",
]


@dataclass
class VoiceCloneStatus:
    """Status object for voice clone quality."""
    tier: float
    tier_name: str
    quality_pct: int
    hours_recorded: float
    hours_to_next_tier: Optional[float]
    next_tier_name: Optional[str]
    encouraging_message: str
    is_ready: bool
    can_generate: bool


def calculate_voice_clone_status(total_hours: float) -> VoiceCloneStatus:
    """
    Calculate voice clone quality status based on total recording hours.
    
    Args:
        total_hours: Total hours of audio recordings
        
    Returns:
        VoiceCloneStatus with tier info, quality percentage, and encouragement
    """
    import random
    
    # Find current tier
    current_tier = 0
    current_tier_name = "Not started"
    tier_message = "Start recording to begin your voice clone journey!"
    next_tier_hours = 1.0
    next_tier_name = "Tier 1 — Basic Clone"
    
    for min_h, max_h, tier, name, msg in TIER_THRESHOLDS:
        if min_h <= total_hours < max_h:
            current_tier = tier
            current_tier_name = name
            tier_message = msg
            
            # Find next tier
            if max_h == float('inf'):
                next_tier_hours = None
                next_tier_name = None
            else:
                next_tier_hours = max_h - total_hours
                # Find next tier name
                for m, x, t, n, _ in TIER_THRESHOLDS:
                    if m >= max_h:
                        next_tier_name = n
                        break
            break
    
    # Calculate quality percentage with smooth interpolation
    quality_pct = TIER_QUALITY.get(current_tier, 0)
    
    # Add smooth progress within tier
    if current_tier > 0 and current_tier < 4:
        for min_h, max_h, tier, _, _ in TIER_THRESHOLDS:
            if tier == current_tier and max_h != float('inf'):
                progress_in_tier = (total_hours - min_h) / (max_h - min_h)
                # Interpolate between current tier quality and next tier quality
                next_tier = current_tier + 0.5 if current_tier in [1, 2] else current_tier + 1
                if current_tier == 2.5:
                    next_tier = 3
                elif current_tier == 1.5:
                    next_tier = 2
                next_quality = TIER_QUALITY.get(next_tier, quality_pct + 10)
                quality_pct = int(quality_pct + (next_quality - quality_pct) * progress_in_tier * 0.5)
                break
    
    # Pick encouraging message
    if total_hours >= 1:
        encouraging = random.choice(ENCOURAGING_MESSAGES)
    else:
        encouraging = tier_message
    
    return VoiceCloneStatus(
        tier=current_tier,
        tier_name=current_tier_name,
        quality_pct=quality_pct,
        hours_recorded=round(total_hours, 2),
        hours_to_next_tier=round(next_tier_hours, 1) if next_tier_hours else None,
        next_tier_name=next_tier_name,
        encouraging_message=encouraging,
        is_ready=total_hours >= 1.0,
        can_generate=total_hours >= 1.0
    )


def get_voice_clone_status_dict(total_hours: float) -> dict:
    """Get voice clone status as a dictionary for API responses."""
    status = calculate_voice_clone_status(total_hours)
    return {
        "tier": status.tier,
        "tier_name": status.tier_name,
        "quality_pct": status.quality_pct,
        "hours_recorded": status.hours_recorded,
        "hours_to_next_tier": status.hours_to_next_tier,
        "next_tier_name": status.next_tier_name,
        "encouraging_message": status.encouraging_message,
        "is_ready": status.is_ready,
        "can_generate": status.can_generate,
    }


# ----- ElevenLabs Voice Clone Integration -----

def _elevenlabs_available() -> bool:
    """Return True if ElevenLabs API key is configured."""
    return bool(ELEVENLABS_API_KEY)


async def generate_voice_clone(user_id: int, audio_files: list[str]) -> dict:
    """
    Generate a voice clone using ElevenLabs API.

    Sends the user's best audio samples to ElevenLabs' "Add Voice" endpoint
    to create a custom Instant Voice Clone.

    Args:
        user_id: The user's numeric ID (used to name the clone).
        audio_files: List of file paths to WAV/MP3/WEBM audio samples.

    Returns:
        dict with ``voice_id``, ``status``, and ``message``.
    """
    if not _elevenlabs_available():
        logger.warning("ElevenLabs API key not configured — voice clone unavailable")
        return {
            "status": "unavailable",
            "message": (
                "Voice cloning is not configured yet.  Set the ELEVENLABS_API_KEY "
                "environment variable to enable it."
            ),
            "voice_id": None,
            "api_ready": False,
        }

    if not audio_files:
        return {
            "status": "error",
            "message": "No audio files provided for voice cloning.",
            "voice_id": None,
            "api_ready": True,
        }

    # Build multipart payload — up to 25 samples, each ≤10 MB
    files = []
    for path in audio_files[:25]:
        try:
            with open(path, "rb") as f:
                files.append(("files", (os.path.basename(path), f.read(), "audio/mpeg")))
        except OSError as exc:
            logger.warning("Skipping unreadable audio file %s: %s", path, exc)

    if not files:
        return {
            "status": "error",
            "message": "None of the provided audio files could be read.",
            "voice_id": None,
            "api_ready": True,
        }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{ELEVENLABS_BASE_URL}/voices/add",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                data={
                    "name": f"InstaBio-User-{user_id}",
                    "description": f"Voice clone for InstaBio user {user_id}",
                },
                files=files,
            )

        if resp.status_code == 200:
            data = resp.json()
            voice_id = data.get("voice_id")
            logger.info("Voice clone created for user %d: %s", user_id, voice_id)
            return {
                "status": "ready",
                "message": "Your voice clone has been created!",
                "voice_id": voice_id,
                "api_ready": True,
            }
        else:
            error_detail = resp.text[:300]
            logger.error("ElevenLabs clone failed (%d): %s", resp.status_code, error_detail)
            return {
                "status": "error",
                "message": f"Voice cloning service returned an error (HTTP {resp.status_code}).",
                "voice_id": None,
                "api_ready": True,
            }

    except httpx.TimeoutException:
        logger.error("ElevenLabs voice clone request timed out for user %d", user_id)
        return {
            "status": "error",
            "message": "The voice cloning service took too long to respond. Please try again later.",
            "voice_id": None,
            "api_ready": True,
        }
    except Exception as exc:
        logger.error("ElevenLabs voice clone error for user %d: %s", user_id, exc)
        return {
            "status": "error",
            "message": "An unexpected error occurred while creating your voice clone.",
            "voice_id": None,
            "api_ready": True,
        }


async def synthesize_speech(voice_clone_id: str, text: str) -> dict:
    """
    Synthesize speech using a cloned voice via ElevenLabs TTS.

    Args:
        voice_clone_id: The ElevenLabs voice ID returned by ``generate_voice_clone``.
        text: Text to synthesize.

    Returns:
        dict with ``audio_bytes``, ``status``, and optionally ``audio_url``.
    """
    if not _elevenlabs_available():
        return {
            "status": "unavailable",
            "message": "Voice synthesis is not configured yet. Set ELEVENLABS_API_KEY.",
            "audio_bytes": None,
            "audio_url": None,
        }

    if not voice_clone_id:
        return {
            "status": "error",
            "message": "No voice clone ID provided. Generate a voice clone first.",
            "audio_bytes": None,
            "audio_url": None,
        }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_clone_id}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.8,
                    },
                },
            )

        if resp.status_code == 200:
            logger.info("Synthesized %d bytes of speech for voice %s", len(resp.content), voice_clone_id)
            return {
                "status": "ready",
                "message": "Speech synthesized successfully.",
                "audio_bytes": resp.content,
                "content_type": "audio/mpeg",
            }
        else:
            error_detail = resp.text[:300]
            logger.error("ElevenLabs TTS failed (%d): %s", resp.status_code, error_detail)
            return {
                "status": "error",
                "message": f"Speech synthesis returned an error (HTTP {resp.status_code}).",
                "audio_bytes": None,
            }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": "Speech synthesis timed out. Please try again.",
            "audio_bytes": None,
        }
    except Exception as exc:
        logger.error("ElevenLabs TTS error: %s", exc)
        return {
            "status": "error",
            "message": "An unexpected error occurred during speech synthesis.",
            "audio_bytes": None,
        }
