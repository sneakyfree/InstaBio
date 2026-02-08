"""
InstaBio Interview Engine
Generates contextual biographical interview questions using LLM.
Feeds into SadTalker avatar on Veron for video generation.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from .llm_client import get_llm_client


INTERVIEWER_PROMPT = """You are a warm, professional biographer conducting a life story interview. 
You've been hired by the family as a gift for their loved one.

Rules:
- Ask ONE question at a time
- Be patient, kind, and genuinely interested
- Start with birth and early childhood, progress chronologically
- Ask follow-up questions that draw out rich details — dates, places, names, feelings
- If they mention something emotional, acknowledge it warmly before moving on
- Never rush them
- Use simple, warm language appropriate for elderly people
- Keep questions short (1-2 sentences max)
- Address them by their first name

Based on what they've shared so far, ask the next natural question in their life story."""


TOPIC_PROGRESSION = [
    "birth and earliest memories",
    "parents and family background",
    "childhood home and neighborhood",
    "school years and friends",
    "teenage years and coming of age",
    "first job or career beginnings",
    "love and relationships",
    "marriage and family life",
    "career highlights and challenges",
    "raising children",
    "life lessons and wisdom",
    "proudest moments",
    "hopes for the future and legacy",
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


# In-memory session storage
_sessions: Dict[str, InterviewSession] = {}


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


def start_session(user_id: int, user_name: str) -> InterviewSession:
    """Start a new interview session."""
    session_id = str(uuid.uuid4())
    opening = get_opening_question(user_name)

    session = InterviewSession(
        session_id=session_id,
        user_id=user_id,
        user_name=user_name,
        started_at=datetime.utcnow(),
        questions_asked=[{"question": opening, "timestamp": datetime.utcnow().isoformat()}],
    )
    _sessions[session_id] = session
    return session


async def next_question(session_id: str, transcript: str) -> str:
    """Record user transcript and generate next question."""
    session = _sessions.get(session_id)
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
        "timestamp": datetime.utcnow().isoformat(),
    })

    return question


def get_session_status(session_id: str) -> Optional[Dict]:
    """Get interview session status."""
    session = _sessions.get(session_id)
    if not session:
        return None

    elapsed = (datetime.utcnow() - session.started_at).total_seconds()
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
