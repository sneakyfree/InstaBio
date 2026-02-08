"""
InstaBio Soul Status Module
Tracks readiness for the "Soul" - the interactive AI clone.

Soul Requirements:
- 10+ hours of recording (for personality & content)
- Biography generated (for structured memories)
- Voice clone ready (for speaking)

The Soul is the crown jewel - an AI that knows your stories,
speaks in your voice, and can have conversations with family.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SoulRequirement:
    """A single requirement for the Soul."""
    id: str
    name: str
    description: str
    is_met: bool
    progress_pct: int
    progress_detail: str


@dataclass
class SoulStatus:
    """Status object for Soul readiness."""
    readiness_pct: int
    tier: str
    tier_description: str
    requirements: List[SoulRequirement]
    requirements_met: List[str]
    requirements_remaining: List[str]
    next_step: str
    encouraging_message: str
    is_ready: bool


def calculate_soul_status(
    recording_hours: float,
    biography_status: str,  # 'none', 'processing', 'ready'
    biography_chapters_ready: int = 0,
    biography_chapters_total: int = 5,
    voice_clone_ready: bool = False,
    avatar_ready: bool = False,
) -> SoulStatus:
    """
    Calculate Soul readiness based on all requirements.
    
    Args:
        recording_hours: Total hours of audio recordings
        biography_status: Status of biography generation
        biography_chapters_ready: Number of biography chapters completed
        biography_chapters_total: Total planned biography chapters
        voice_clone_ready: Whether voice clone is available
        avatar_ready: Whether avatar is available
        
    Returns:
        SoulStatus with requirement checklist and overall progress
    """
    requirements = []
    requirements_met = []
    requirements_remaining = []
    
    # ----- Requirement 1: Recording Hours (10+ hours) -----
    recording_target = 10.0
    recording_progress = min(100, int((recording_hours / recording_target) * 100))
    recording_met = recording_hours >= recording_target
    
    if recording_met:
        recording_detail = f"✓ {recording_hours:.1f} hours recorded"
        requirements_met.append("recording_complete")
    elif recording_hours >= 1:
        recording_detail = f"{recording_hours:.1f} / {recording_target} hours ({recording_target - recording_hours:.1f} to go)"
        requirements_met.append("recording_started")
    else:
        recording_detail = f"Just getting started! {recording_target - recording_hours:.1f} hours to go"
    
    requirements.append(SoulRequirement(
        id="recording",
        name="10+ Hours of Stories",
        description="Record at least 10 hours of your life stories for the Soul to know you deeply",
        is_met=recording_met,
        progress_pct=recording_progress,
        progress_detail=recording_detail,
    ))
    
    if not recording_met:
        requirements_remaining.append("recording_complete")
    
    # ----- Requirement 2: Biography Generated -----
    if biography_status == 'ready' and biography_chapters_ready >= 3:
        bio_met = True
        bio_progress = 100
        bio_detail = f"✓ {biography_chapters_ready} chapters ready"
        requirements_met.append("biography_ready")
    elif biography_status == 'processing':
        bio_met = False
        bio_progress = int((biography_chapters_ready / max(biography_chapters_total, 1)) * 80 + 20)
        bio_detail = f"Processing... {biography_chapters_ready}/{biography_chapters_total} chapters"
        requirements_met.append("biography_started")
        requirements_remaining.append("biography_ready")
    elif biography_chapters_ready > 0:
        bio_met = False
        bio_progress = int((biography_chapters_ready / max(biography_chapters_total, 1)) * 80)
        bio_detail = f"{biography_chapters_ready}/{biography_chapters_total} chapters generated"
        requirements_remaining.append("biography_ready")
    else:
        bio_met = False
        bio_progress = 0
        bio_detail = "Not started yet — record more stories first!"
        requirements_remaining.append("biography_ready")
    
    requirements.append(SoulRequirement(
        id="biography",
        name="Biography Generated",
        description="Your life story organized into chapters helps the Soul understand your journey",
        is_met=bio_met,
        progress_pct=bio_progress,
        progress_detail=bio_detail,
    ))
    
    # ----- Requirement 3: Voice Clone Ready -----
    if voice_clone_ready:
        voice_met = True
        voice_progress = 100
        voice_detail = "✓ Voice clone ready"
        requirements_met.append("voice_ready")
    elif recording_hours >= 1:
        voice_met = False
        voice_progress = 50
        voice_detail = "Voice clone available but not activated"
        requirements_remaining.append("voice_ready")
    else:
        voice_met = False
        voice_progress = int((recording_hours / 1.0) * 50)
        voice_detail = f"Need {max(0, 1 - recording_hours):.1f} more hours for basic voice"
        requirements_remaining.append("voice_ready")
    
    requirements.append(SoulRequirement(
        id="voice",
        name="Voice Clone",
        description="Your voice clone lets the Soul speak as you",
        is_met=voice_met,
        progress_pct=voice_progress,
        progress_detail=voice_detail,
    ))
    
    # ----- Optional Bonus: Avatar -----
    if avatar_ready:
        requirements_met.append("avatar_ready")
    
    requirements.append(SoulRequirement(
        id="avatar",
        name="Avatar (Optional)",
        description="An avatar lets the Soul appear visually when talking",
        is_met=avatar_ready,
        progress_pct=100 if avatar_ready else 0,
        progress_detail="✓ Avatar ready" if avatar_ready else "Upload photos to create your avatar",
    ))
    
    # ----- Calculate Overall Readiness -----
    # Recording = 40%, Biography = 35%, Voice = 25% (Avatar is bonus)
    core_requirements_pct = (
        recording_progress * 0.40 +
        bio_progress * 0.35 +
        voice_progress * 0.25
    )
    readiness_pct = int(core_requirements_pct)
    
    # Determine tier
    if readiness_pct >= 100:
        tier = "Ready"
        tier_description = "Your Soul is ready to awaken!"
        is_ready = True
    elif readiness_pct >= 75:
        tier = "Almost There"
        tier_description = "Just a bit more and your Soul will be complete"
        is_ready = False
    elif readiness_pct >= 50:
        tier = "Growing"
        tier_description = "Your Soul is taking shape"
        is_ready = False
    elif readiness_pct >= 25:
        tier = "Emerging"
        tier_description = "The foundation of your Soul is being built"
        is_ready = False
    else:
        tier = "Beginning"
        tier_description = "Your Soul's journey has just begun"
        is_ready = False
    
    # Determine next step
    if not recording_met:
        remaining_hours = recording_target - recording_hours
        next_step = f"Record {remaining_hours:.1f} more hours of stories"
    elif not bio_met:
        next_step = "Generate your biography to organize your memories"
    elif not voice_met:
        next_step = "Activate your voice clone"
    else:
        next_step = "Your Soul is ready! Family members can now have conversations with your AI."
    
    # Encouraging message
    if readiness_pct < 25:
        encouraging = "Every story you record brings your Soul closer to life. Keep going!"
    elif readiness_pct < 50:
        encouraging = "You're making great progress! Your Soul is learning who you are."
    elif readiness_pct < 75:
        encouraging = "Wonderful! Your Soul is really starting to take shape."
    elif readiness_pct < 100:
        encouraging = "So close! Just a few more steps and your legacy will be complete."
    else:
        encouraging = "Your Soul is alive! Your family can now talk to you forever."
    
    return SoulStatus(
        readiness_pct=readiness_pct,
        tier=tier,
        tier_description=tier_description,
        requirements=requirements,
        requirements_met=requirements_met,
        requirements_remaining=requirements_remaining,
        next_step=next_step,
        encouraging_message=encouraging,
        is_ready=is_ready,
    )


def get_soul_status_dict(
    recording_hours: float,
    biography_status: str = 'none',
    biography_chapters_ready: int = 0,
    biography_chapters_total: int = 5,
    voice_clone_ready: bool = False,
    avatar_ready: bool = False,
) -> dict:
    """Get Soul status as a dictionary for API responses."""
    status = calculate_soul_status(
        recording_hours=recording_hours,
        biography_status=biography_status,
        biography_chapters_ready=biography_chapters_ready,
        biography_chapters_total=biography_chapters_total,
        voice_clone_ready=voice_clone_ready,
        avatar_ready=avatar_ready,
    )
    
    return {
        "readiness_pct": status.readiness_pct,
        "tier": status.tier,
        "tier_description": status.tier_description,
        "requirements": [
            {
                "id": req.id,
                "name": req.name,
                "description": req.description,
                "is_met": req.is_met,
                "progress_pct": req.progress_pct,
                "progress_detail": req.progress_detail,
            }
            for req in status.requirements
        ],
        "requirements_met": status.requirements_met,
        "requirements_remaining": status.requirements_remaining,
        "next_step": status.next_step,
        "encouraging_message": status.encouraging_message,
        "is_ready": status.is_ready,
    }


# ----- Placeholder for Soul interaction -----

async def activate_soul(user_id: int) -> dict:
    """
    Placeholder for Soul activation.
    
    In production, this would:
    1. Build RAG index from transcripts
    2. Fine-tune LoRA on user's speech patterns
    3. Configure voice clone integration
    4. Set up family access controls
    
    For now, returns a mock response.
    """
    return {
        "status": "pending",
        "message": "Soul activation coming soon! We're building the AI that will carry your legacy.",
        "features_planned": [
            "Conversational AI grounded in your stories",
            "Never invents memories — only uses what you recorded",
            "Speaks in your voice",
            "Family access controls",
        ],
        "api_ready": False,
    }


async def chat_with_soul(user_id: int, message: str, family_member_id: Optional[int] = None) -> dict:
    """
    Placeholder for Soul conversation.
    
    In production, this would:
    1. Process the message
    2. Search RAG index for relevant memories
    3. Generate response in user's style
    4. Convert to speech using voice clone
    
    For now, returns a mock response.
    """
    return {
        "status": "not_implemented",
        "message": "Soul conversations coming soon!",
        "response": None,
        "audio_url": None,
    }
