"""
InstaBio Retroactive Journal Generation
Creates journal entries from timeline and entity data
"""

import json
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

from .llm_client import get_llm_client, OllamaClient
from .entity_extraction import ExtractionResult, Event, DateMention, ConfidenceLevel


class JournalGranularity(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    YEARLY = "yearly"


@dataclass
class JournalEntry:
    """A single journal entry."""
    date: str
    date_display: str  # Human-readable date
    granularity: JournalGranularity
    text: str
    source_sessions: List[str]
    events_referenced: List[str]
    is_reconstructed: bool = True
    confidence: ConfidenceLevel = ConfidenceLevel.INFERRED
    
    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "date_display": self.date_display,
            "granularity": self.granularity.value,
            "text": self.text,
            "source_sessions": self.source_sessions,
            "events_referenced": self.events_referenced,
            "is_reconstructed": self.is_reconstructed,
            "confidence": self.confidence.value
        }


@dataclass
class JournalCollection:
    """A collection of journal entries."""
    entries: List[JournalEntry]
    author_name: str
    generated_at: str
    total_entries: int
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "author_name": self.author_name,
            "generated_at": self.generated_at,
            "total_entries": self.total_entries,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end
        }


JOURNAL_ENTRY_PROMPT = """You are writing a journal entry as if you were the person speaking. This entry is being reconstructed from their oral history recordings.

DATE: {date}
GRANULARITY: {granularity}

EVENTS THAT HAPPENED:
{events}

ORIGINAL WORDS FROM RECORDINGS:
\"\"\"
{transcripts}
\"\"\"

PLACES MENTIONED: {places}
PEOPLE MENTIONED: {people}

Write a first-person journal entry for this date/period. Rules:
1. Write as if you are the person, using "I" and present tense
2. ONLY include information from the recordings - never invent
3. Capture their voice and personality
4. Keep it intimate and personal, like a real diary
5. Reference specific details they mentioned
6. Length: 2-4 paragraphs

Return JSON only:
{{
    "entry_text": "The journal entry...",
    "key_moments": ["moment 1", "moment 2"],
    "emotional_tone": "hopeful|nostalgic|joyful|reflective|bittersweet|determined"
}}

JSON response:"""


class JournalGenerator:
    """
    Generates retroactive journal entries from extracted timeline data.
    """
    
    def __init__(self, llm_client: Optional[OllamaClient] = None):
        self.llm = llm_client or get_llm_client()
    
    def determine_granularity(self, date_mention: DateMention) -> JournalGranularity:
        """
        Determine the appropriate journal granularity based on the date mention.
        """
        date_str = date_mention.date.lower()
        date_type = date_mention.date_type.lower()
        
        # Check for specific day mentions
        if date_type == "day" or re.search(r'\b\d{1,2}(st|nd|rd|th)\b', date_str):
            return JournalGranularity.DAILY
        
        # Check for month mentions
        months = ['january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november', 'december']
        if any(m in date_str for m in months) or date_type == "month":
            return JournalGranularity.MONTHLY
        
        # Check for season mentions
        seasons = ['spring', 'summer', 'fall', 'autumn', 'winter']
        if any(s in date_str for s in seasons) or date_type == "season":
            return JournalGranularity.SEASONAL
        
        # Check for approximate time phrases
        if any(phrase in date_str for phrase in ['early', 'late', 'mid', 'around']):
            return JournalGranularity.SEASONAL
        
        # Default to yearly for year-only mentions
        if re.match(r'^(19|20)\d{2}$', date_str.strip()):
            return JournalGranularity.YEARLY
        
        return JournalGranularity.SEASONAL
    
    def format_date_display(
        self,
        date: str,
        granularity: JournalGranularity
    ) -> str:
        """
        Format a date string for display based on granularity.
        """
        date_str = date.strip()
        
        if granularity == JournalGranularity.YEARLY:
            return f"A Year in {date_str}"
        elif granularity == JournalGranularity.SEASONAL:
            # Try to extract season and year
            seasons = ['spring', 'summer', 'fall', 'autumn', 'winter']
            for season in seasons:
                if season in date_str.lower():
                    year_match = re.search(r'(19|20)\d{2}', date_str)
                    year = year_match.group() if year_match else ""
                    return f"{season.capitalize()} {year}".strip()
            return date_str.title()
        elif granularity == JournalGranularity.MONTHLY:
            return date_str.title()
        else:
            return date_str
    
    async def generate_entry(
        self,
        date: str,
        events: List[Event],
        transcripts: List[Dict[str, str]],
        people: List[str],
        places: List[str],
        granularity: JournalGranularity
    ) -> JournalEntry:
        """
        Generate a single journal entry for a date/period.
        """
        # Format events
        events_str = "\n".join([
            f"- {e.description} (type: {e.event_type})"
            for e in events[:5]
        ]) or "No specific events recorded"
        
        # Combine relevant transcripts
        transcript_text = "\n".join([
            t.get("text", "")[:500] for t in transcripts[:3]
        ]) or "No transcript text available"
        
        prompt = JOURNAL_ENTRY_PROMPT.format(
            date=date,
            granularity=granularity.value,
            events=events_str,
            transcripts=transcript_text,
            places=", ".join(places[:5]) or "Not specified",
            people=", ".join(people[:5]) or "Not specified"
        )
        
        response = await self.llm.generate(
            prompt=prompt,
            temperature=0.8,  # Slightly higher for more creative/personal writing
            max_tokens=2048
        )
        
        if not response.success:
            return self._placeholder_entry(date, events, granularity)
        
        try:
            text = self._clean_json(response.text)
            data = json.loads(text)
            
            return JournalEntry(
                date=date,
                date_display=self.format_date_display(date, granularity),
                granularity=granularity,
                text=data.get("entry_text", ""),
                source_sessions=[t.get("session_id", "") for t in transcripts if t.get("session_id")],
                events_referenced=[e.description for e in events],
                is_reconstructed=True,
                confidence=ConfidenceLevel.INFERRED
            )
            
        except json.JSONDecodeError:
            return self._placeholder_entry(date, events, granularity)
    
    def _placeholder_entry(
        self,
        date: str,
        events: List[Event],
        granularity: JournalGranularity
    ) -> JournalEntry:
        """Generate a placeholder entry when generation fails."""
        event_text = events[0].description if events else "No events recorded"
        
        return JournalEntry(
            date=date,
            date_display=self.format_date_display(date, granularity),
            granularity=granularity,
            text=f"*Reconstructed from memory*\n\nAround this time: {event_text}. More recordings will help fill in the details.",
            source_sessions=[],
            events_referenced=[e.description for e in events],
            is_reconstructed=True,
            confidence=ConfidenceLevel.INFERRED
        )
    
    async def generate_journal(
        self,
        user_name: str,
        extraction: ExtractionResult,
        timeline: List[Dict],
        transcripts: List[Dict[str, str]]
    ) -> JournalCollection:
        """
        Generate a complete journal from extraction data.
        """
        entries = []
        
        # Group timeline events by date
        date_events: Dict[str, List[Event]] = {}
        date_granularities: Dict[str, JournalGranularity] = {}
        
        for event in extraction.events:
            if event.date:
                date_key = event.date
                if date_key not in date_events:
                    date_events[date_key] = []
                date_events[date_key].append(event)
        
        # Add dates from date mentions
        for date_mention in extraction.dates:
            date_key = date_mention.date
            granularity = self.determine_granularity(date_mention)
            date_granularities[date_key] = granularity
            
            if date_key not in date_events:
                # Create a pseudo-event from the date mention
                if date_mention.event:
                    date_events[date_key] = [Event(
                        event_type="mention",
                        description=date_mention.event,
                        date=date_key,
                        date_confidence=date_mention.confidence
                    )]
        
        # Get people and places for context
        people = [p.name for p in extraction.people]
        places = [p.name for p in extraction.places]
        
        # Generate entries for each date
        for date, events in sorted(date_events.items(), key=lambda x: self._sort_key(x[0])):
            granularity = date_granularities.get(date, JournalGranularity.SEASONAL)
            
            entry = await self.generate_entry(
                date=date,
                events=events,
                transcripts=transcripts[:3],
                people=people,
                places=places,
                granularity=granularity
            )
            entries.append(entry)
        
        # Sort entries chronologically
        entries.sort(key=lambda e: self._sort_key(e.date))
        
        return JournalCollection(
            entries=entries,
            author_name=user_name,
            generated_at=datetime.utcnow().isoformat(),
            total_entries=len(entries),
            date_range_start=entries[0].date if entries else None,
            date_range_end=entries[-1].date if entries else None
        )
    
    def _sort_key(self, date: str) -> int:
        """Generate a sort key for a date string."""
        # Extract year
        match = re.search(r'(19|20)\d{2}', str(date))
        if match:
            year = int(match.group())
            # Adjust for seasonal modifiers
            if "early" in date.lower():
                return year * 100 + 1
            elif "late" in date.lower():
                return year * 100 + 12
            elif "spring" in date.lower():
                return year * 100 + 3
            elif "summer" in date.lower():
                return year * 100 + 6
            elif "fall" in date.lower() or "autumn" in date.lower():
                return year * 100 + 9
            elif "winter" in date.lower():
                return year * 100 + 12
            return year * 100 + 6  # Default to mid-year
        return 999999  # Unknown dates go to end
    
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
    
    def get_entries_by_date_range(
        self,
        journal: JournalCollection,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[JournalEntry]:
        """
        Filter journal entries by date range.
        """
        entries = journal.entries
        
        if start_date:
            start_key = self._sort_key(start_date)
            entries = [e for e in entries if self._sort_key(e.date) >= start_key]
        
        if end_date:
            end_key = self._sort_key(end_date)
            entries = [e for e in entries if self._sort_key(e.date) <= end_key]
        
        return entries
    
    def get_entry_by_date(
        self,
        journal: JournalCollection,
        date: str
    ) -> Optional[JournalEntry]:
        """
        Get a specific journal entry by date.
        """
        for entry in journal.entries:
            if entry.date.lower() == date.lower():
                return entry
        return None


# Global generator
_journal_generator: Optional[JournalGenerator] = None


def get_journal_generator() -> JournalGenerator:
    """Get or create the global journal generator."""
    global _journal_generator
    if _journal_generator is None:
        _journal_generator = JournalGenerator()
    return _journal_generator
