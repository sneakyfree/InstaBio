"""
InstaBio Soul Module
Tracks readiness for the "Soul" - the interactive AI clone.
Implements RAG-based grounded conversation using transcript keyword search
and LLM generation via the existing llm_client.

Soul Requirements:
- 10+ hours of recording (for personality & content)
- Biography generated (for structured memories)
- Voice clone ready (for speaking)

The Soul is the crown jewel - an AI that knows your stories,
speaks in your voice, and can have conversations with family.
"""

import re
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


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
        biography_chapters_ready: Number of biography chapters generated
        biography_chapters_total: Target number of chapters
        voice_clone_ready: Whether voice clone is available
        avatar_ready: Whether avatar is available
    """
    requirements = []

    # Requirement 1: Recording hours (10+ hours for full Soul)
    rec_met = recording_hours >= 10
    rec_pct = min(int((recording_hours / 10) * 100), 100)
    requirements.append(SoulRequirement(
        id="recording",
        name="Recording Hours",
        description="Record 10+ hours of your life story",
        is_met=rec_met,
        progress_pct=rec_pct,
        progress_detail=f"{recording_hours:.1f}/10 hours recorded",
    ))

    # Requirement 2: Biography generated
    bio_met = biography_status == "ready"
    bio_pct = 0
    if biography_status == "processing":
        bio_pct = int((biography_chapters_ready / max(biography_chapters_total, 1)) * 80)
    elif biography_status == "ready":
        bio_pct = 100
    requirements.append(SoulRequirement(
        id="biography",
        name="Biography",
        description="Generate your life biography from recordings",
        is_met=bio_met,
        progress_pct=bio_pct,
        progress_detail=(
            f"{biography_chapters_ready}/{biography_chapters_total} chapters"
            if biography_status != "none"
            else "Not started"
        ),
    ))

    # Requirement 3: Voice clone
    vc_met = voice_clone_ready
    vc_pct = 100 if vc_met else min(int((recording_hours / 1) * 100), 99)
    requirements.append(SoulRequirement(
        id="voice_clone",
        name="Voice Clone",
        description="Create a clone of your voice (1+ hours)",
        is_met=vc_met,
        progress_pct=vc_pct,
        progress_detail="Ready!" if vc_met else f"{recording_hours:.1f}/1 hours needed",
    ))

    # Requirement 4: Avatar (optional but contributes to readiness)
    av_met = avatar_ready
    av_pct = 100 if av_met else 0
    requirements.append(SoulRequirement(
        id="avatar",
        name="Avatar",
        description="Upload a photo for your visual avatar",
        is_met=av_met,
        progress_pct=av_pct,
        progress_detail="Ready!" if av_met else "Upload a photo",
    ))

    # Calculate overall readiness
    # Weights: recording 40%, biography 30%, voice 20%, avatar 10%
    weights = {"recording": 40, "biography": 30, "voice_clone": 20, "avatar": 10}
    pcts = {r.id: r.progress_pct for r in requirements}
    readiness_pct = (
        pcts["recording"] * weights["recording"]
        + pcts["biography"] * weights["biography"]
        + pcts["voice_clone"] * weights["voice_clone"]
        + pcts["avatar"] * weights["avatar"]
    ) // 100

    # Determine tier
    met = [r.id for r in requirements if r.is_met]
    remaining = [r.id for r in requirements if not r.is_met]
    is_ready = len(remaining) == 0

    if readiness_pct < 10:
        tier = "Dormant"
        tier_desc = "The Soul needs more of your story. Keep recording!"
    elif readiness_pct < 40:
        tier = "Awakening"
        tier_desc = "Your Soul is beginning to take shape."
    elif readiness_pct < 70:
        tier = "Forming"
        tier_desc = "Your Soul knows many of your stories now."
    elif readiness_pct < 100:
        tier = "Almost Ready"
        tier_desc = "Just a few more pieces and your Soul will be complete."
    else:
        tier = "Alive"
        tier_desc = "Your Soul is ready! Family can talk to you anytime."

    # Next step
    if not rec_met:
        next_step = f"Record {max(10 - recording_hours, 0):.1f} more hours of your story."
    elif not bio_met:
        next_step = "Generate your biography from the Progress page."
    elif not vc_met:
        next_step = "Your voice clone is almost ready — keep recording!"
    elif not av_met:
        next_step = "Upload a photo to give your Soul a face."
    else:
        next_step = "Your Soul is complete! Share it with family."

    # Encouraging message
    messages = {
        "Dormant": "Every word you record brings your Soul closer to life.",
        "Awakening": "Your stories are taking root. Keep going!",
        "Forming": "Family will be amazed — your Soul already knows so much.",
        "Almost Ready": "You're so close! Just a little more and your legacy is forever.",
        "Alive": "Your Soul is alive. Your family can hear your stories anytime.",
    }

    return SoulStatus(
        readiness_pct=readiness_pct,
        tier=tier,
        tier_description=tier_desc,
        requirements=requirements,
        requirements_met=met,
        requirements_remaining=remaining,
        next_step=next_step,
        encouraging_message=messages.get(tier, ""),
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
        recording_hours, biography_status,
        biography_chapters_ready, biography_chapters_total,
        voice_clone_ready, avatar_ready,
    )
    return {
        "readiness_pct": status.readiness_pct,
        "tier": status.tier,
        "tier_description": status.tier_description,
        "requirements": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "is_met": r.is_met,
                "progress_pct": r.progress_pct,
                "progress_detail": r.progress_detail,
            }
            for r in status.requirements
        ],
        "requirements_met": status.requirements_met,
        "requirements_remaining": status.requirements_remaining,
        "next_step": status.next_step,
        "encouraging_message": status.encouraging_message,
        "is_ready": status.is_ready,
    }


# ---------------------------------------------------------------------------
# Soul RAG — keyword-based retrieval + LLM grounded chat
# ---------------------------------------------------------------------------

# In-memory keyword index per user:  user_id → { keyword → [transcript_chunk] }
_soul_indexes: Dict[int, Dict[str, List[str]]] = {}
_soul_active: Dict[int, bool] = {}

_STOP_WORDS = {
    "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "and", "but", "or",
    "nor", "not", "so", "yet", "for", "at", "by", "from", "in", "into",
    "of", "on", "to", "with", "about", "it", "its", "i", "me", "my",
    "we", "our", "you", "your", "he", "she", "his", "her", "they",
    "them", "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "how", "when", "where", "why", "if", "then", "than",
    "just", "very", "really", "like", "also", "well", "oh", "yeah",
    "um", "uh", "okay", "ok",
}


def _tokenize(text: str) -> List[str]:
    """Simple whitespace tokenizer with stop-word removal."""
    return [
        w for w in re.findall(r"[a-z']+", text.lower())
        if len(w) > 2 and w not in _STOP_WORDS
    ]


def _chunk_text(text: str, chunk_size: int = 300) -> List[str]:
    """Split text into overlapping chunks of roughly *chunk_size* words."""
    words = text.split()
    chunks = []
    step = max(chunk_size // 2, 50)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk.strip())
    return chunks


def _build_index(transcripts: List[str]) -> Dict[str, List[str]]:
    """Build a simple inverted keyword index over transcript chunks."""
    index: Dict[str, List[str]] = defaultdict(list)
    for text in transcripts:
        for chunk in _chunk_text(text):
            for token in set(_tokenize(chunk)):
                index[token].append(chunk)
    return dict(index)


def _search_index(index: Dict[str, List[str]], query: str, top_k: int = 5) -> List[str]:
    """Return the *top_k* most relevant chunks for *query* by keyword overlap."""
    tokens = _tokenize(query)
    if not tokens:
        return []

    scores: Dict[int, float] = {}  # chunk_id → score
    chunk_list: List[str] = []
    seen: set = set()

    for token in tokens:
        for chunk in index.get(token, []):
            cid = id(chunk)
            if cid not in seen:
                seen.add(cid)
                chunk_list.append(chunk)
                scores[cid] = 0
            scores[cid] += 1

    # Sort by score descending
    ranked = sorted(chunk_list, key=lambda c: scores.get(id(c), 0), reverse=True)
    return ranked[:top_k]


# ----- Public API -----

async def activate_soul(user_id: int) -> dict:
    """
    Activate the Soul for a user by building a keyword index
    over all their transcripts.

    In production this would also:
    - Build a vector embedding index
    - Fine-tune a LoRA on speech patterns
    - Configure voice clone + avatar integration

    For MVP, we build a simple keyword index that enables
    grounded retrieval-augmented conversation.
    """
    from . import database as db

    transcripts = await db.get_user_transcripts(user_id)
    if not transcripts:
        return {
            "status": "error",
            "message": "No transcripts found. Record some stories first!",
            "is_active": False,
        }

    texts = [t["text"] for t in transcripts if t.get("text")]
    if not texts:
        return {
            "status": "error",
            "message": "No transcript text found. Record some stories first!",
            "is_active": False,
        }

    # Build keyword index
    index = _build_index(texts)
    _soul_indexes[user_id] = index
    _soul_active[user_id] = True

    total_chunks = sum(len(v) for v in index.values())
    logger.info(
        "Soul activated for user %d: %d transcripts, %d keywords, %d chunks indexed",
        user_id, len(texts), len(index), total_chunks,
    )

    return {
        "status": "active",
        "message": "Your Soul is ready! Family can start asking questions.",
        "is_active": True,
        "transcripts_indexed": len(texts),
        "keywords_indexed": len(index),
    }


async def chat_with_soul(
    user_id: int,
    message: str,
    family_member_id: Optional[int] = None,
) -> dict:
    """
    Chat with the Soul.  Uses keyword RAG to find relevant transcript
    chunks, then sends them + the question to the LLM with strict
    grounding rules (no hallucination).

    Args:
        user_id:  The user whose Soul to query.
        message:  The family member's question.
        family_member_id:  Optional ID for audit logging.

    Returns:
        dict with ``response``, ``citations``, and ``status``.
    """
    from .llm_client import get_llm_client

    # Check if soul is active
    if not _soul_active.get(user_id):
        return {
            "status": "inactive",
            "response": (
                "My Soul hasn't been activated yet. "
                "Go to the Progress page and activate it first!"
            ),
            "citations": [],
        }

    index = _soul_indexes.get(user_id, {})
    if not index:
        return {
            "status": "error",
            "response": "Something went wrong — my memory index is empty.",
            "citations": [],
        }

    # Retrieve relevant chunks
    relevant_chunks = _search_index(index, message, top_k=5)

    # Build the prompt with strict grounding rules
    if relevant_chunks:
        context = "\n\n---\n\n".join(relevant_chunks)
        system_prompt = (
            "You are embodying a real person based ONLY on their recorded oral history. "
            "You speak in first person, using their vocabulary and speaking style.\n\n"
            "ABSOLUTE RULES:\n"
            "1. ONLY use information from the CONTEXT below. NEVER invent memories.\n"
            "2. If the context does not contain relevant information, say something like: "
            "\"You know, I don't think I ever talked about that. "
            "Ask me about something else!\"\n"
            "3. Speak warmly and naturally, as if chatting with family.\n"
            "4. Keep responses 2-4 sentences unless the topic warrants more.\n"
            "5. NEVER provide medical, legal, or financial advice.\n"
            "6. If asked if you are an AI, say: \"I'm an AI built from Grandma's recordings. "
            "I try to answer the way she would, based on what she told me.\"\n\n"
            f"CONTEXT FROM RECORDINGS:\n{context}"
        )
    else:
        system_prompt = (
            "You are embodying a real person based on their recorded oral history. "
            "However, NO relevant recordings were found for this question. "
            "Respond warmly and say you don't remember talking about that topic. "
            "Suggest they ask about something else."
        )

    llm = get_llm_client()
    response = await llm.generate(
        prompt=message,
        system=system_prompt,
        temperature=0.7,
        max_tokens=512,
    )

    if not response.success:
        return {
            "status": "error",
            "response": (
                "Oh dear, I'm having trouble thinking right now. "
                "Can you try asking again?"
            ),
            "citations": [],
            "error": response.error,
        }

    # Build citation snippets (first 100 chars of each used chunk)
    citations = [
        {"snippet": chunk[:100] + "..." if len(chunk) > 100 else chunk}
        for chunk in relevant_chunks
    ]

    return {
        "status": "ok",
        "response": response.text,
        "citations": citations,
        "model": response.model,
    }
