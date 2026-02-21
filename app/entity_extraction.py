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


def extract_entities_quick(text: str) -> Dict[str, list]:
    """
    Lightweight regex-based entity extraction.
    Works without LLM — useful as a fallback or quick scan.
    """
    # Person names: 2-4 consecutive capitalized words
    names = list(set(re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b', text)))

    # Years: 4-digit numbers 1900-2026
    years = list(set(re.findall(r'\b(19\d{2}|20[0-2]\d)\b', text)))

    # Places: City, State patterns or known US states
    places = list(set(re.findall(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming))\b',
        text
    )))

    # Life events: sentences with key life milestones
    event_keywords = r'\b(born|married|graduated|moved|died|retired|started|founded|enlisted|promoted|transferred|divorced|widowed|immigrated|emigrated)\b'
    sentences = re.split(r'[.!?]', text)
    events = [s.strip() for s in sentences if re.search(event_keywords, s, re.IGNORECASE) and len(s.strip()) > 10]

    return {"names": names[:20], "years": sorted(years), "places": places[:10], "events": events[:10]}


# ---------------------------------------------------------------------------
# Pure-regex, fully-offline entity extraction (no LLM required)
# ---------------------------------------------------------------------------

# Common English stop-words / false-positive names to skip
_STOP_NAMES = {
    "I", "He", "She", "It", "We", "They", "The", "This", "That", "These",
    "Those", "My", "His", "Her", "Our", "Your", "Its", "Mr", "Mrs", "Ms",
    "But", "And", "Then", "Well", "Yes", "Yeah", "No", "So", "Oh", "Now",
    "Just", "Like", "There", "Here", "What", "When", "Where", "Who", "How",
    "About", "After", "Before", "During", "Would", "Could", "Should",
    "Also", "Very", "Really", "Maybe", "Actually", "Probably", "Because",
    "Still", "Even", "Back", "Over", "Some", "Every", "However", "Although",
    "Never", "Always", "Sometimes", "Once", "First", "Last", "Next", "Only",
    "Many", "Much", "Most", "Other", "Another", "Each", "Both", "Few",
    "Several", "Such", "Same", "One", "Two", "Three", "Four", "Five",
    "Six", "Seven", "Eight", "Nine", "Ten", "Anyway", "Anyhow", "Indeed",
    "Perhaps", "Certainly", "Definitely", "Absolutely", "Basically",
    "Essentially", "Obviously", "Literally", "Quite", "Rather", "Enough",
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Spring", "Summer", "Fall", "Autumn", "Winter", "Christmas", "Easter",
    "Thanksgiving", "Halloween", "New",
}

# US state abbreviations and full names (for place detection)
_US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
}

# Relationship keywords that often precede or follow a person's name
_RELATIONSHIP_WORDS = {
    "mother", "mom", "mama", "father", "dad", "papa", "brother", "sister",
    "son", "daughter", "husband", "wife", "uncle", "aunt", "cousin",
    "grandfather", "grandpa", "grandmother", "grandma", "nephew", "niece",
    "friend", "neighbor", "neighbour", "boss", "teacher", "coach",
    "pastor", "doctor", "nurse", "partner",
}

# Place-type keyword hints
_PLACE_KEYWORDS = {
    "street", "avenue", "road", "boulevard", "lane", "drive", "court",
    "circle", "highway", "square", "bridge", "park", "lake", "river",
    "mountain", "hill", "valley", "island", "beach", "county", "city",
    "town", "village",
}

# Event-type keyword mapping
_EVENT_PATTERNS: List[tuple] = [
    ("birth",     re.compile(r"\b(?:born|birth)\b", re.I)),
    ("death",     re.compile(r"\b(?:died|passed away|funeral|death|passed on)\b", re.I)),
    ("marriage",  re.compile(r"\b(?:married|wedding|engaged|engagement|wed)\b", re.I)),
    ("move",      re.compile(r"\b(?:moved to|relocated|moved from|moved back)\b", re.I)),
    ("job",       re.compile(r"\b(?:hired|fired|retired|started working|got a job|new job|promoted|promotion|worked at|worked for)\b", re.I)),
    ("education", re.compile(r"\b(?:graduated|enrolled|school|college|university|diploma|degree|studied)\b", re.I)),
    ("military",  re.compile(r"\b(?:enlisted|deployed|served|military|army|navy|marines|air force|drafted|discharge)\b", re.I)),
]

# ---- Compiled patterns ----
_RE_CAPITALIZED_NAME = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)
_RE_RELATIONSHIP_BEFORE = re.compile(
    r"\b(?:my|his|her|our)\s+(" + "|".join(_RELATIONSHIP_WORDS) + r")\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
    re.I,
)
_RE_RELATIONSHIP_AFTER = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),?\s+(?:my|his|her|our)\s+(" + "|".join(_RELATIONSHIP_WORDS) + r")\b",
    re.I,
)
_RE_YEAR = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")
_RE_DECADE = re.compile(r"\b(?:the\s+)?((?:early|mid|late)\s+)?(\d{4})s\b", re.I)
_RE_FULL_DATE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_RE_MONTH_YEAR = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4})\b",
    re.I,
)
_RE_SEASON_YEAR = re.compile(
    r"\b((?:spring|summer|fall|autumn|winter)\s+(?:of\s+)?\d{4})\b", re.I
)
_RE_PLACE_WITH_STATE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),\s*([A-Z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)
_RE_STREET_ADDRESS = re.compile(
    r"\b(\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*\s+(?:" + "|".join(_PLACE_KEYWORDS) + r"))\b",
    re.I,
)

# State abbreviation set for quick lookup
_STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def _sentence_around(text: str, match_start: int, match_end: int, radius: int = 120) -> str:
    """Return a snippet of text surrounding a regex match."""
    start = max(0, match_start - radius)
    end = min(len(text), match_end + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def extract_entities(
    transcript: str,
    session_id: Optional[str] = None,
) -> ExtractionResult:
    """
    Extract people, places, dates, and events from *transcript* using only
    regex heuristics.  Pure Python, no LLM, fully offline.

    Returns an ``ExtractionResult`` identical in shape to what
    ``EntityExtractor.extract()`` produces, so callers can swap freely.
    """
    if not transcript or len(transcript.strip()) < 10:
        return ExtractionResult(
            people=[], places=[], dates=[], events=[],
            success=True, source_session=session_id,
        )

    # ---- People ----
    people_map: Dict[str, Person] = {}

    # Pattern 1: "my <relationship> <Name>"
    for m in _RE_RELATIONSHIP_BEFORE.finditer(transcript):
        rel, name = m.group(1).strip(), m.group(2).strip()
        key = name.lower()
        if name.split()[0] in _STOP_NAMES:
            continue
        if key not in people_map:
            people_map[key] = Person(
                name=name,
                relationship=rel.lower(),
                context=_sentence_around(transcript, m.start(), m.end()),
                confidence=ConfidenceLevel.EXACT,
            )
        else:
            people_map[key].mentions += 1
            if not people_map[key].relationship:
                people_map[key].relationship = rel.lower()

    # Pattern 2: "<Name>, my <relationship>"
    for m in _RE_RELATIONSHIP_AFTER.finditer(transcript):
        name, rel = m.group(1).strip(), m.group(2).strip()
        key = name.lower()
        if name.split()[0] in _STOP_NAMES:
            continue
        if key not in people_map:
            people_map[key] = Person(
                name=name,
                relationship=rel.lower(),
                context=_sentence_around(transcript, m.start(), m.end()),
                confidence=ConfidenceLevel.EXACT,
            )
        else:
            people_map[key].mentions += 1

    # Pattern 3: Capitalized multi-word names (≥2 words → likely a person)
    for m in _RE_CAPITALIZED_NAME.finditer(transcript):
        name = m.group(1).strip()
        words = name.split()
        if len(words) < 2:
            continue  # single capitalised word is too noisy
        if any(w in _STOP_NAMES for w in words):
            continue
        key = name.lower()
        if key in people_map:
            people_map[key].mentions += 1
        else:
            people_map[key] = Person(
                name=name,
                context=_sentence_around(transcript, m.start(), m.end()),
                confidence=ConfidenceLevel.APPROXIMATE,
            )

    # ---- Places ----
    places_map: Dict[str, Place] = {}

    # Pattern 1: "City, ST" or "City, State"
    for m in _RE_PLACE_WITH_STATE.finditer(transcript):
        city, state = m.group(1).strip(), m.group(2).strip()
        if state in _STATE_ABBREVS or state in _US_STATES:
            full = f"{city}, {state}"
            key = full.lower()
            if key not in places_map:
                places_map[key] = Place(
                    name=full,
                    place_type="city",
                    context=_sentence_around(transcript, m.start(), m.end()),
                    confidence=ConfidenceLevel.EXACT,
                )

    # Pattern 2: Street addresses ("123 Main Street")
    for m in _RE_STREET_ADDRESS.finditer(transcript):
        addr = m.group(1).strip()
        key = addr.lower()
        if key not in places_map:
            places_map[key] = Place(
                name=addr,
                place_type="address",
                context=_sentence_around(transcript, m.start(), m.end()),
                confidence=ConfidenceLevel.EXACT,
            )

    # Pattern 3: US state full names appearing standalone
    for state in _US_STATES:
        if state in transcript:
            key = state.lower()
            if key not in places_map:
                idx = transcript.index(state)
                places_map[key] = Place(
                    name=state,
                    place_type="state",
                    context=_sentence_around(transcript, idx, idx + len(state)),
                    confidence=ConfidenceLevel.EXACT,
                )

    # ---- Dates ----
    dates_list: List[DateMention] = []
    seen_dates: set = set()

    # Full dates: "March 15, 1968"
    for m in _RE_FULL_DATE.finditer(transcript):
        raw = m.group(1).strip()
        if raw not in seen_dates:
            seen_dates.add(raw)
            dates_list.append(DateMention(
                date=raw, date_type="day",
                confidence=ConfidenceLevel.EXACT,
            ))

    # Month + Year: "June 1955"
    for m in _RE_MONTH_YEAR.finditer(transcript):
        raw = m.group(1).strip()
        if raw not in seen_dates:
            seen_dates.add(raw)
            dates_list.append(DateMention(
                date=raw, date_type="month",
                confidence=ConfidenceLevel.EXACT,
            ))

    # Season + Year: "summer of 1972"
    for m in _RE_SEASON_YEAR.finditer(transcript):
        raw = m.group(1).strip()
        if raw not in seen_dates:
            seen_dates.add(raw)
            dates_list.append(DateMention(
                date=raw, date_type="season",
                confidence=ConfidenceLevel.APPROXIMATE,
            ))

    # Decades: "the late 1960s"
    for m in _RE_DECADE.finditer(transcript):
        qualifier = (m.group(1) or "").strip()
        decade = m.group(2)
        raw = f"{qualifier} {decade}s".strip()
        if raw not in seen_dates:
            seen_dates.add(raw)
            dates_list.append(DateMention(
                date=raw, date_type="approximate",
                confidence=ConfidenceLevel.APPROXIMATE,
            ))

    # Standalone years: "1968"
    for m in _RE_YEAR.finditer(transcript):
        raw = m.group(1)
        if raw not in seen_dates:
            seen_dates.add(raw)
            dates_list.append(DateMention(
                date=raw, date_type="year",
                confidence=ConfidenceLevel.EXACT,
            ))

    # ---- Events ----
    events_list: List[Event] = []
    seen_events: set = set()

    for event_type, pattern in _EVENT_PATTERNS:
        for m in pattern.finditer(transcript):
            snippet = _sentence_around(transcript, m.start(), m.end(), radius=200)
            evt_key = (event_type, snippet[:80])
            if evt_key in seen_events:
                continue
            seen_events.add(evt_key)

            # Try to find a year near the keyword
            nearby_text = transcript[max(0, m.start() - 100): min(len(transcript), m.end() + 100)]
            year_match = _RE_YEAR.search(nearby_text)
            date_str = year_match.group(1) if year_match else None

            # Collect nearby people / places
            nearby_people = [
                p.name for p in people_map.values()
                if p.name.lower() in nearby_text.lower()
            ]
            nearby_places = [
                p.name for p in places_map.values()
                if p.name.lower() in nearby_text.lower()
            ]

            events_list.append(Event(
                event_type=event_type,
                description=snippet.strip(),
                date=date_str,
                date_confidence=(
                    ConfidenceLevel.EXACT if date_str else ConfidenceLevel.INFERRED
                ),
                people_involved=nearby_people,
                places_involved=nearby_places,
                source_text=m.group(0),
            ))

    # Remove any "people" that were also detected as places (city names etc.)
    place_name_keys = {k for k in places_map}
    people_cleaned = {
        k: v for k, v in people_map.items() if k not in place_name_keys
    }

    return ExtractionResult(
        people=list(people_cleaned.values()),
        places=list(places_map.values()),
        dates=dates_list,
        events=events_list,
        success=True,
        source_session=session_id,
    )


# Singleton extractor
_extractor: Optional[EntityExtractor] = None


def get_extractor() -> EntityExtractor:
    """Get or create the global entity extractor."""
    global _extractor
    if _extractor is None:
        _extractor = EntityExtractor()
    return _extractor
