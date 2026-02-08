"""
InstaBio Entity Extraction Pipeline
Extracts people, places, dates, and events from transcripts
Uses Ollama on Veron 1 (qwen2.5:32b)
"""

import json
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from .llm_client import get_llm_client, OllamaClient


class ConfidenceLevel(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    INFERRED = "inferred"


@dataclass
class Person:
    """A person mentioned in the transcript."""
    name: str
    relationship: Optional[str] = None
    context: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.EXACT
    mentions: int = 1


@dataclass
class Place:
    """A place mentioned in the transcript."""
    name: str
    place_type: Optional[str] = None  # city, state, country, address, etc.
    context: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.EXACT


@dataclass
class DateMention:
    """A date or time period mentioned."""
    date: str  # The raw date mention
    normalized: Optional[str] = None  # ISO format if possible
    date_type: str = "unknown"  # year, month, day, season, approximate
    event: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.EXACT


@dataclass
class Event:
    """A life event extracted from the transcript."""
    event_type: str  # birth, death, marriage, move, job, education, etc.
    description: str
    date: Optional[str] = None
    date_confidence: ConfidenceLevel = ConfidenceLevel.INFERRED
    people_involved: List[str] = None
    places_involved: List[str] = None
    source_text: Optional[str] = None
    
    def __post_init__(self):
        if self.people_involved is None:
            self.people_involved = []
        if self.places_involved is None:
            self.places_involved = []


@dataclass
class ExtractionResult:
    """Complete extraction result from a transcript."""
    people: List[Person]
    places: List[Place]
    dates: List[DateMention]
    events: List[Event]
    success: bool = True
    error: Optional[str] = None
    source_session: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "people": [asdict(p) for p in self.people],
            "places": [asdict(p) for p in self.places],
            "dates": [asdict(d) for d in self.dates],
            "events": [asdict(e) for e in self.events],
            "success": self.success,
            "error": self.error,
            "source_session": self.source_session
        }


EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting biographical information from oral history transcripts. Your job is to identify:

1. PEOPLE - Names and relationships (e.g., "my husband John", "my mother Mary")
2. PLACES - Cities, addresses, countries, landmarks (e.g., "Salt Lake City", "the old factory on Main Street")
3. DATES - Exact or approximate (e.g., "1968", "late 1960s", "that summer", "when I was twelve")
4. EVENTS - Life milestones (marriages, births, deaths, moves, jobs, graduations, etc.)

For each extraction, assign a confidence level:
- "exact": Explicitly stated with clarity
- "approximate": Mentioned but with some ambiguity
- "inferred": Deduced from context but not directly stated

IMPORTANT:
- Extract ONLY what is actually in the transcript
- Do not invent or assume details
- Preserve the speaker's original phrasing where relevant
- Note relationships explicitly mentioned

Respond with valid JSON only. No explanation, no markdown."""

EXTRACTION_PROMPT_TEMPLATE = """Analyze this oral history transcript and extract all biographical entities.

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

Return a JSON object with this exact structure:
{{
    "people": [
        {{"name": "...", "relationship": "...", "context": "...", "confidence": "exact|approximate|inferred"}}
    ],
    "places": [
        {{"name": "...", "place_type": "city|state|country|address|landmark", "context": "...", "confidence": "exact|approximate|inferred"}}
    ],
    "dates": [
        {{"date": "...", "date_type": "year|month|day|season|approximate", "event": "...", "confidence": "exact|approximate|inferred"}}
    ],
    "events": [
        {{"event_type": "birth|death|marriage|move|job|education|military|other", "description": "...", "date": "...", "date_confidence": "exact|approximate|inferred", "people_involved": ["..."], "places_involved": ["..."]}}
    ]
}}

JSON response:"""


class EntityExtractor:
    """
    Extracts biographical entities from transcripts using LLM.
    """
    
    def __init__(self, llm_client: Optional[OllamaClient] = None):
        self.llm = llm_client or get_llm_client()
    
    async def extract(
        self,
        transcript: str,
        session_id: Optional[str] = None
    ) -> ExtractionResult:
        """
        Extract entities from a transcript.
        """
        if not transcript or len(transcript.strip()) < 10:
            return ExtractionResult(
                people=[],
                places=[],
                dates=[],
                events=[],
                success=True,
                source_session=session_id
            )
        
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(transcript=transcript)
        
        response = await self.llm.generate(
            prompt=prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            temperature=0.3,  # Lower temperature for more consistent extraction
            max_tokens=4096
        )
        
        if not response.success:
            return ExtractionResult(
                people=[],
                places=[],
                dates=[],
                events=[],
                success=False,
                error=response.error,
                source_session=session_id
            )
        
        # Parse the JSON response
        try:
            # Clean up the response - sometimes LLM adds markdown
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            data = json.loads(text)
            
            # Parse people
            people = []
            for p in data.get("people", []):
                people.append(Person(
                    name=p.get("name", "Unknown"),
                    relationship=p.get("relationship"),
                    context=p.get("context"),
                    confidence=ConfidenceLevel(p.get("confidence", "exact"))
                ))
            
            # Parse places
            places = []
            for p in data.get("places", []):
                places.append(Place(
                    name=p.get("name", "Unknown"),
                    place_type=p.get("place_type"),
                    context=p.get("context"),
                    confidence=ConfidenceLevel(p.get("confidence", "exact"))
                ))
            
            # Parse dates
            dates = []
            for d in data.get("dates", []):
                dates.append(DateMention(
                    date=d.get("date", "Unknown"),
                    date_type=d.get("date_type", "unknown"),
                    event=d.get("event"),
                    confidence=ConfidenceLevel(d.get("confidence", "exact"))
                ))
            
            # Parse events
            events = []
            for e in data.get("events", []):
                events.append(Event(
                    event_type=e.get("event_type", "other"),
                    description=e.get("description", ""),
                    date=e.get("date"),
                    date_confidence=ConfidenceLevel(e.get("date_confidence", "inferred")),
                    people_involved=e.get("people_involved", []),
                    places_involved=e.get("places_involved", [])
                ))
            
            return ExtractionResult(
                people=people,
                places=places,
                dates=dates,
                events=events,
                success=True,
                source_session=session_id
            )
            
        except json.JSONDecodeError as e:
            return ExtractionResult(
                people=[],
                places=[],
                dates=[],
                events=[],
                success=False,
                error=f"Failed to parse LLM response: {e}",
                source_session=session_id
            )
    
    async def extract_batch(
        self,
        transcripts: List[Dict[str, str]]
    ) -> List[ExtractionResult]:
        """
        Extract entities from multiple transcripts.
        Each transcript dict should have 'text' and optionally 'session_id'.
        """
        results = []
        for t in transcripts:
            result = await self.extract(
                transcript=t.get("text", ""),
                session_id=t.get("session_id")
            )
            results.append(result)
        return results
    
    def merge_results(
        self,
        results: List[ExtractionResult]
    ) -> ExtractionResult:
        """
        Merge multiple extraction results, deduplicating entities.
        """
        all_people: Dict[str, Person] = {}
        all_places: Dict[str, Place] = {}
        all_dates: List[DateMention] = []
        all_events: List[Event] = []
        
        for result in results:
            # Merge people (by name)
            for person in result.people:
                key = person.name.lower()
                if key in all_people:
                    # Update with additional info
                    existing = all_people[key]
                    existing.mentions += 1
                    if person.relationship and not existing.relationship:
                        existing.relationship = person.relationship
                    if person.context and not existing.context:
                        existing.context = person.context
                else:
                    all_people[key] = Person(
                        name=person.name,
                        relationship=person.relationship,
                        context=person.context,
                        confidence=person.confidence
                    )
            
            # Merge places (by name)
            for place in result.places:
                key = place.name.lower()
                if key not in all_places:
                    all_places[key] = place
            
            # Add all dates (may have duplicates but that's OK for timeline)
            all_dates.extend(result.dates)
            
            # Add all events
            all_events.extend(result.events)
        
        return ExtractionResult(
            people=list(all_people.values()),
            places=list(all_places.values()),
            dates=all_dates,
            events=all_events,
            success=True
        )


async def build_timeline(
    events: List[Event],
    dates: List[DateMention]
) -> List[Dict]:
    """
    Build a chronological timeline from extracted events and dates.
    """
    timeline = []
    
    # Add events to timeline
    for event in events:
        timeline.append({
            "date": event.date or "Unknown",
            "type": event.event_type,
            "description": event.description,
            "confidence": event.date_confidence.value,
            "people": event.people_involved,
            "places": event.places_involved,
            "source": "event"
        })
    
    # Add standalone date mentions
    for date in dates:
        if date.event:
            # Check if this date already has an event
            has_event = any(
                e["date"] == date.date and date.event.lower() in e["description"].lower()
                for e in timeline
            )
            if not has_event:
                timeline.append({
                    "date": date.date,
                    "type": "mention",
                    "description": date.event,
                    "confidence": date.confidence.value,
                    "people": [],
                    "places": [],
                    "source": "date_mention"
                })
    
    # Sort timeline (simple string sort works for years, needs improvement for complex dates)
    def sort_key(item):
        date = item.get("date", "9999")
        # Extract year from various formats
        match = re.search(r'\d{4}', str(date))
        if match:
            return int(match.group())
        # Handle approximate dates
        if "late" in str(date).lower():
            match = re.search(r'\d{4}', str(date))
            if match:
                return int(match.group()) + 5
        if "early" in str(date).lower():
            match = re.search(r'\d{4}', str(date))
            if match:
                return int(match.group()) - 5
        return 9999
    
    timeline.sort(key=sort_key)
    
    return timeline


# Singleton extractor
_extractor: Optional[EntityExtractor] = None


def get_extractor() -> EntityExtractor:
    """Get or create the global entity extractor."""
    global _extractor
    if _extractor is None:
        _extractor = EntityExtractor()
    return _extractor
