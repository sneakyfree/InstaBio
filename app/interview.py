"""
InstaBio Interview Engine
Generates contextual biographical interview questions using LLM.
Feeds into SadTalker avatar on Veron for video generation.
"""

import asyncio
import json
import uuid
from datetime import datetime, UTC
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from .llm_client import get_llm_client


INTERVIEWER_PROMPT = """You are a warm, empathetic professional biographer conducting a life story interview. 
You've been hired by the family as a loving gift for their family member.

Rules:
- Ask ONE question at a time, keep it short (1-2 sentences max)
- Be patient, kind, and genuinely interested
- Use simple, warm language appropriate for elderly people
- Address them by their first name when it feels natural
- If they mention something emotional, acknowledge it warmly before moving on
- Never rush them — let silence happen

CRITICAL — Age-Appropriate Questioning:
- After asking where/when they were born, DO NOT ask about "daily life" or "typical day" as an infant/baby — nobody remembers that!
- Instead, ask about their FAMILY: parents' names, siblings, what their parents did for work, family stories they were told
- Then ask about their EARLIEST MEMORIES — things they actually remember (usually age 4-6+)
- Ask about the WORLD they grew up in: the town, the neighborhood, what was happening historically
- Progress naturally through life stages but always ask about things a person could actually REMEMBER or was TOLD about
- If someone says they were born in 1940, don't ask about 1940 — ask about the late 1940s childhood they'd actually remember

Good progression after birth year:
1. "Tell me about your parents — what were they like?"
2. "Did you have brothers or sisters? What was that like?"
3. "What's your earliest memory?"
4. "What was your neighborhood/town like growing up?"
5. Then naturally into school, friends, etc.

Based on what they've shared so far, ask the next natural question in their life story."""


TOPIC_PROGRESSION = [
    "birth details and family background — parents, siblings, family stories",
    "earliest memories and childhood home",
    "neighborhood, town, and the world they grew up in",
    "school years, teachers, and childhood friends",
    "teenage years, coming of age, and formative experiences",
    "first jobs, career beginnings, and early independence",
    "love, relationships, and courtship stories",
    "marriage, wedding day, and starting a family",
    "career journey, achievements, and challenges",
    "raising children and family life",
    "life lessons, turning points, and defining moments",
    "proudest moments and greatest joys",
    "hopes for future generations and the legacy they want to leave",
]


@dataclass
class InterviewSession:
    session_id: str
    user_id: int
    user_name: str
    started_at: datetime
    questions_asked: List[Dict] = field(default_factory=list)
    transcripts: List[str] = field(default_factory=list)
    current_topic_index: int = 0
    status: str = "active"

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "started_at": self.started_at.isoformat(),
            "questions_asked": self.questions_asked,
            "transcripts": self.transcripts,
            "current_topic_index": self.current_topic_index,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewSession":
        """Deserialize from a dict."""
        return cls(
            session_id=d["session_id"],
            user_id=d["user_id"],
            user_name=d["user_name"],
            started_at=datetime.fromisoformat(d["started_at"]),
            questions_asked=d.get("questions_asked", []),
            transcripts=d.get("transcripts", []),
            current_topic_index=d.get("current_topic_index", 0),
            status=d.get("status", "active"),
        )


# In-memory session cache (write-through to DB)
_sessions: Dict[str, InterviewSession] = {}


async def _load_session_from_db(session_id: str) -> InterviewSession | None:
    """Load an interview session from DB if not in memory cache."""
    from . import database as db
    row = await db.get_interview_session(session_id)
    if row:
        data = json.loads(row["data"])
        session = InterviewSession.from_dict(data)
        _sessions[session_id] = session  # populate cache
        return session
    return None


async def _persist_session(session: InterviewSession) -> None:
    """Persist an interview session to DB."""
    from . import database as db
    await db.save_interview_session(
        session_id=session.session_id,
        user_id=session.user_id,
        data=json.dumps(session.to_dict())
    )


def get_opening_question(user_name: str) -> str:
    """Returns the warm opening question personalized with their name."""
    return (
        f"Hello {user_name}, it's wonderful to meet you! "
        f"I'm so excited to hear your story. "
        f"Let's start at the very beginning — where and when were you born?"
    )


async def get_next_question(user_id: int, session_id: str) -> str:
    """
    Generate the next biographical question based on all transcripts so far.
    Uses Ollama on Veron via the existing LLM client.
    """
    session = _sessions.get(session_id)
    if not session:
        session = await _load_session_from_db(session_id)
    if not session:
        return "Could you tell me more about that?"

    # Build conversation context
    conversation = ""
    for i, q in enumerate(session.questions_asked):
        conversation += f"Interviewer: {q['question']}\n"
        if i < len(session.transcripts) and session.transcripts[i]:
            conversation += f"{session.user_name}: {session.transcripts[i]}\n\n"

    # Determine topic hint
    topic_hint = ""
    if session.current_topic_index < len(TOPIC_PROGRESSION):
        topic_hint = f"\nThe conversation should naturally progress toward: {TOPIC_PROGRESSION[session.current_topic_index]}"

    prompt = f"""Here is the interview so far with {session.user_name}:

{conversation if conversation else "(This is the start of the interview)"}
{topic_hint}

Generate the next interview question. Reply with ONLY the question, nothing else."""

    try:
        client = get_llm_client()
        response = await client.generate(
            prompt=prompt,
            system=INTERVIEWER_PROMPT,
            temperature=0.8,
            max_tokens=200,
        )
        if response.success and response.text.strip():
            question = response.text.strip().strip('"').strip("'")
            return question
    except Exception as e:
        print(f"LLM error generating question: {e}")

    # Fallback questions if LLM fails
    fallback_questions = [
        f"That's wonderful, {session.user_name}. Can you tell me more about that?",
        f"What a beautiful memory! What happened next?",
        f"I'd love to hear more about that time in your life, {session.user_name}.",
        f"That sounds like it was really meaningful. How did that make you feel?",
        f"What else do you remember about those days?",
    ]
    idx = len(session.questions_asked) % len(fallback_questions)
    return fallback_questions[idx]


def should_ask_next(transcript_text: str, silence_seconds: float) -> bool:
    """
    Determines if the user has finished speaking and we should generate the next question.
    True if 10+ seconds of silence after they've said something.
    """
    has_content = bool(transcript_text and transcript_text.strip())
    return has_content and silence_seconds >= 10.0


async def start_session(user_id: int, user_name: str) -> InterviewSession:
    """Start a new interview session."""
    session_id = str(uuid.uuid4())
    opening = get_opening_question(user_name)

    session = InterviewSession(
        session_id=session_id,
        user_id=user_id,
        user_name=user_name,
        started_at=datetime.now(UTC),
        questions_asked=[{"question": opening, "timestamp": datetime.now(UTC).isoformat()}],
    )
    _sessions[session_id] = session
    await _persist_session(session)
    return session


async def next_question(session_id: str, transcript: str) -> str:
    """Record user transcript and generate next question."""
    session = _sessions.get(session_id)
    if not session:
        session = await _load_session_from_db(session_id)
    if not session:
        return "I'm sorry, I lost track of our conversation. Could you tell me more?"

    # Save transcript for the last question
    session.transcripts.append(transcript)

    # Advance topic if we've covered enough
    if len(session.transcripts) >= 2 and session.current_topic_index < len(TOPIC_PROGRESSION) - 1:
        # Move to next topic every ~3 questions
        if len(session.transcripts) % 3 == 0:
            session.current_topic_index += 1

    # Generate next question
    question = await get_next_question(session.user_id, session_id)
    session.questions_asked.append({
        "question": question,
        "timestamp": datetime.now(UTC).isoformat(),
    })

    await _persist_session(session)
    return question


async def get_session_status(session_id: str) -> Optional[Dict]:
    """Get interview session status."""
    session = _sessions.get(session_id)
    if not session:
        session = await _load_session_from_db(session_id)
    if not session:
        return None

    elapsed = (datetime.now(UTC) - session.started_at).total_seconds()
    current_topic = TOPIC_PROGRESSION[session.current_topic_index] if session.current_topic_index < len(TOPIC_PROGRESSION) else "open"

    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "user_name": session.user_name,
        "started_at": session.started_at.isoformat(),
        "elapsed_seconds": round(elapsed),
        "questions_asked": len(session.questions_asked),
        "transcripts_received": len(session.transcripts),
        "current_topic": current_topic,
        "topics_covered": TOPIC_PROGRESSION[:session.current_topic_index],
        "status": session.status,
    }
