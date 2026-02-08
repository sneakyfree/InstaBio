"""
InstaBio Biography Generation
Generates polished life narratives from transcripts and extracted entities
"""

import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from .llm_client import get_llm_client, OllamaClient
from .entity_extraction import ExtractionResult, Event, ConfidenceLevel


class BiographyStyle(str, Enum):
    VERBATIM = "verbatim"      # Minimal editing, preserves original voice
    POLISHED = "polished"      # Professional prose
    STORYBOOK = "storybook"    # Simplified for younger readers


@dataclass
class Citation:
    """A citation linking to source audio."""
    session_uuid: str
    chunk_index: Optional[int] = None
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None
    original_text: Optional[str] = None


@dataclass
class Paragraph:
    """A paragraph in the biography with source attribution."""
    text: str
    citations: List[Citation]
    confidence_notes: List[str]  # Notes about uncertain dates/facts
    
    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "citations": [asdict(c) for c in self.citations],
            "confidence_notes": self.confidence_notes
        }


@dataclass
class Chapter:
    """A chapter in the biography."""
    number: int
    title: str
    paragraphs: List[Paragraph]
    time_period: Optional[str] = None
    summary: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "number": self.number,
            "title": self.title,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "time_period": self.time_period,
            "summary": self.summary
        }


@dataclass
class Biography:
    """A complete generated biography."""
    title: str
    subtitle: Optional[str]
    author_name: str
    chapters: List[Chapter]
    style: BiographyStyle
    generated_at: str
    status: str = "complete"  # complete, partial, draft
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "author_name": self.author_name,
            "chapters": [c.to_dict() for c in self.chapters],
            "style": self.style.value,
            "generated_at": self.generated_at,
            "status": self.status
        }


CHAPTER_PLANNING_PROMPT = """You are planning the chapters for a life memoir. Based on the following timeline and events, suggest appropriate chapter divisions.

TIMELINE:
{timeline}

EVENTS:
{events}

PEOPLE MENTIONED:
{people}

PLACES MENTIONED:
{places}

Suggest 3-8 chapters that would naturally organize this person's life story. Consider:
- Childhood and early life
- Education and formative years
- Career and professional life
- Marriage and family
- Major life changes and moves
- Reflections and wisdom

Return JSON only:
{{
    "chapters": [
        {{"number": 1, "title": "...", "time_period": "...", "events_to_include": ["..."], "summary": "..."}}
    ]
}}

JSON response:"""


NARRATIVE_GENERATION_PROMPT = """You are writing a chapter for someone's life memoir. Write in first person, as if the person is telling their own story.

CHAPTER: {chapter_title}
TIME PERIOD: {time_period}

SOURCE TRANSCRIPTS (what they actually said):
\"\"\"
{transcripts}
\"\"\"

EXTRACTED EVENTS FOR THIS CHAPTER:
{events}

STYLE: {style}
- verbatim: Preserve their exact words and phrasing as much as possible. Minimal editing.
- polished: Clean up the prose but maintain their voice and personality.
- storybook: Simplify for younger readers while keeping the warmth and truth.

RULES:
1. ONLY use information from the transcripts - never invent details
2. Keep their actual phrases and expressions when they're powerful
3. Mark any uncertain dates with [approximately] or [around]
4. Write warm, engaging prose that feels like them talking
5. Each paragraph should naturally flow from one to the next

Write 3-6 paragraphs for this chapter. For each paragraph, note which transcript segments it draws from.

Return JSON only:
{{
    "paragraphs": [
        {{
            "text": "The paragraph text...",
            "source_segments": ["Transcript segment 1...", "Transcript segment 2..."],
            "confidence_notes": ["Note about uncertain date", "Note about inferred relationship"]
        }}
    ]
}}

JSON response:"""


class BiographyGenerator:
    """
    Generates polished biographies from transcripts and extracted entities.
    """
    
    def __init__(self, llm_client: Optional[OllamaClient] = None):
        self.llm = llm_client or get_llm_client()
    
    async def plan_chapters(
        self,
        extraction: ExtractionResult,
        timeline: List[Dict]
    ) -> List[Dict]:
        """
        Plan the chapter structure based on extracted entities and timeline.
        """
        # Format data for the prompt
        timeline_str = "\n".join([
            f"- {t['date']}: {t['description']} (confidence: {t['confidence']})"
            for t in timeline[:20]  # Limit to prevent token overflow
        ])
        
        events_str = "\n".join([
            f"- {e.event_type}: {e.description} ({e.date or 'date unknown'})"
            for e in extraction.events[:15]
        ])
        
        people_str = ", ".join([
            f"{p.name} ({p.relationship or 'relationship unknown'})"
            for p in extraction.people[:10]
        ])
        
        places_str = ", ".join([
            p.name for p in extraction.places[:10]
        ])
        
        prompt = CHAPTER_PLANNING_PROMPT.format(
            timeline=timeline_str or "No timeline data available",
            events=events_str or "No events extracted",
            people=people_str or "No people mentioned",
            places=places_str or "No places mentioned"
        )
        
        response = await self.llm.generate(
            prompt=prompt,
            temperature=0.5,
            max_tokens=2048
        )
        
        if not response.success:
            # Return default chapters
            return self._default_chapters()
        
        try:
            text = self._clean_json(response.text)
            data = json.loads(text)
            return data.get("chapters", self._default_chapters())
        except json.JSONDecodeError:
            return self._default_chapters()
    
    def _default_chapters(self) -> List[Dict]:
        """Default chapter structure when planning fails."""
        return [
            {"number": 1, "title": "Early Years", "time_period": "Childhood", "summary": "The beginning of the story"},
            {"number": 2, "title": "Growing Up", "time_period": "Youth", "summary": "Formative experiences"},
            {"number": 3, "title": "Making My Way", "time_period": "Adulthood", "summary": "Building a life"},
            {"number": 4, "title": "Reflections", "time_period": "Present", "summary": "Looking back with wisdom"}
        ]
    
    async def generate_chapter(
        self,
        chapter_plan: Dict,
        transcripts: List[Dict[str, str]],
        events: List[Event],
        style: BiographyStyle = BiographyStyle.POLISHED
    ) -> Chapter:
        """
        Generate a single chapter narrative.
        """
        # Combine transcripts
        transcript_text = "\n\n---\n\n".join([
            t.get("text", "") for t in transcripts
        ])[:8000]  # Limit length
        
        events_str = "\n".join([
            f"- {e.event_type}: {e.description} ({e.date or 'date unknown'})"
            for e in events[:10]
        ])
        
        prompt = NARRATIVE_GENERATION_PROMPT.format(
            chapter_title=chapter_plan.get("title", "Chapter"),
            time_period=chapter_plan.get("time_period", ""),
            transcripts=transcript_text or "No transcript text available",
            events=events_str or "No specific events",
            style=style.value
        )
        
        response = await self.llm.generate(
            prompt=prompt,
            temperature=0.7,
            max_tokens=4096
        )
        
        if not response.success:
            # Return placeholder chapter
            return self._placeholder_chapter(chapter_plan)
        
        try:
            text = self._clean_json(response.text)
            data = json.loads(text)
            
            paragraphs = []
            for p in data.get("paragraphs", []):
                citations = []
                for seg in p.get("source_segments", []):
                    citations.append(Citation(
                        session_uuid="",  # Would be filled in with actual session
                        original_text=seg[:200]
                    ))
                
                paragraphs.append(Paragraph(
                    text=p.get("text", ""),
                    citations=citations,
                    confidence_notes=p.get("confidence_notes", [])
                ))
            
            return Chapter(
                number=chapter_plan.get("number", 1),
                title=chapter_plan.get("title", "Chapter"),
                paragraphs=paragraphs,
                time_period=chapter_plan.get("time_period"),
                summary=chapter_plan.get("summary")
            )
            
        except json.JSONDecodeError:
            return self._placeholder_chapter(chapter_plan)
    
    def _placeholder_chapter(self, chapter_plan: Dict) -> Chapter:
        """Generate a placeholder chapter when generation fails."""
        return Chapter(
            number=chapter_plan.get("number", 1),
            title=chapter_plan.get("title", "Chapter"),
            paragraphs=[
                Paragraph(
                    text="This chapter is being processed. More recordings will help create a richer narrative.",
                    citations=[],
                    confidence_notes=["Placeholder content - more recordings needed"]
                )
            ],
            time_period=chapter_plan.get("time_period"),
            summary=chapter_plan.get("summary")
        )
    
    async def generate_biography(
        self,
        user_name: str,
        transcripts: List[Dict[str, str]],
        extraction: ExtractionResult,
        timeline: List[Dict],
        style: BiographyStyle = BiographyStyle.POLISHED
    ) -> Biography:
        """
        Generate a complete biography with all chapters.
        """
        from datetime import datetime
        
        # Plan chapters
        chapter_plans = await self.plan_chapters(extraction, timeline)
        
        # Generate each chapter
        chapters = []
        for plan in chapter_plans:
            # Filter events relevant to this chapter
            chapter_events = [
                e for e in extraction.events
                if self._event_matches_chapter(e, plan)
            ]
            
            chapter = await self.generate_chapter(
                chapter_plan=plan,
                transcripts=transcripts,
                events=chapter_events,
                style=style
            )
            chapters.append(chapter)
        
        return Biography(
            title=f"The Story of {user_name}",
            subtitle="A Life in Their Own Words",
            author_name=user_name,
            chapters=chapters,
            style=style,
            generated_at=datetime.utcnow().isoformat(),
            status="complete" if len(chapters) > 1 else "partial"
        )
    
    def _event_matches_chapter(self, event: Event, chapter_plan: Dict) -> bool:
        """Check if an event belongs in a particular chapter."""
        # Simple matching based on time period keywords
        time_period = chapter_plan.get("time_period", "").lower()
        event_desc = event.description.lower()
        event_type = event.event_type.lower()
        
        if "childhood" in time_period or "early" in time_period:
            return "birth" in event_type or "born" in event_desc
        if "education" in time_period or "school" in time_period:
            return "education" in event_type or "school" in event_desc
        if "career" in time_period or "work" in time_period:
            return "job" in event_type or "work" in event_desc
        if "family" in time_period or "marriage" in time_period:
            return "marriage" in event_type or "family" in event_desc
        
        return True  # Include by default
    
    def _clean_json(self, text: str) -> str:
        """Clean up LLM response to valid JSON."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


# Global generator
_generator: Optional[BiographyGenerator] = None


def get_biography_generator() -> BiographyGenerator:
    """Get or create the global biography generator."""
    global _generator
    if _generator is None:
        _generator = BiographyGenerator()
    return _generator
