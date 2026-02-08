"""
InstaBio Voice Clone Status Module
Tracks progress toward voice clone quality based on recording hours.

Voice Clone Tiers:
- 0-1 hours: Not enough data yet (0%)
- 1-2 hours: Tier 1 — Basic clone, recognizable (25%)
- 2-5 hours: Tier 1+ — Improving (40%)
- 5-10 hours: Tier 2 — Good clone, natural (60%)
- 10-20 hours: Tier 2+ — Very good (80%)
- 20-50 hours: Tier 3 — Premium, emotional range (90%)
- 50+ hours: Tier 4 — Ultra, indistinguishable (99%)
"""

from dataclasses import dataclass
from typing import Optional

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


# ----- Placeholder for actual voice clone generation -----

async def generate_voice_clone(user_id: int, audio_files: list[str]) -> dict:
    """
    Placeholder for actual voice clone generation.
    
    In production, this would:
    1. Upload audio to ElevenLabs API or similar
    2. Train a custom voice model
    3. Return the voice clone ID
    
    For now, returns a mock response.
    """
    total_duration = sum(len(f) for f in audio_files)  # Mock calculation
    
    return {
        "status": "pending",
        "message": "Voice clone generation coming soon! We're working on integrating with ElevenLabs.",
        "estimated_quality": "Will depend on your recording hours",
        "api_ready": False,
    }


async def synthesize_speech(voice_clone_id: str, text: str) -> dict:
    """
    Placeholder for voice synthesis.
    
    In production, this would:
    1. Send text to the voice clone API
    2. Return audio data
    
    For now, returns a mock response.
    """
    return {
        "status": "not_implemented",
        "message": "Speech synthesis coming soon!",
        "audio_url": None,
    }
