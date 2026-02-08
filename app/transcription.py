"""
InstaBio Transcription Module
Handles audio transcription using Faster Whisper
"""

import asyncio
import os
from pathlib import Path
from typing import Optional
import logging

# Try to import faster_whisper, but gracefully handle if not installed
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    WhisperModel = None

logger = logging.getLogger(__name__)

# Global model instance (loaded once)
_model: Optional["WhisperModel"] = None
_model_lock = asyncio.Lock()

async def get_whisper_model() -> Optional["WhisperModel"]:
    """
    Get or initialize the Whisper model.
    Uses 'base' model for speed - upgrade to 'large-v3' for production accuracy.
    """
    global _model
    
    if not WHISPER_AVAILABLE:
        logger.warning("faster-whisper not installed. Transcription disabled.")
        return None
    
    async with _model_lock:
        if _model is None:
            logger.info("Loading Whisper model (this may take a moment)...")
            try:
                # Use 'base' for speed, 'large-v3' for accuracy
                # Run in thread pool since model loading is blocking
                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(
                    None,
                    lambda: WhisperModel(
                        "base",  # Options: tiny, base, small, medium, large-v3
                        device="auto",  # auto-detect GPU/CPU
                        compute_type="auto"  # auto-select precision
                    )
                )
                logger.info("✅ Whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                return None
        
        return _model

async def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribe an audio file using Faster Whisper.
    
    Args:
        audio_path: Path to the audio file
        
    Returns:
        dict with 'text', 'language', 'segments', and 'confidence'
    """
    model = await get_whisper_model()
    
    if model is None:
        return {
            "text": "[Transcription unavailable - Whisper not loaded]",
            "language": None,
            "segments": [],
            "confidence": 0.0,
            "error": "Whisper model not available"
        }
    
    if not os.path.exists(audio_path):
        return {
            "text": "",
            "language": None,
            "segments": [],
            "confidence": 0.0,
            "error": f"Audio file not found: {audio_path}"
        }
    
    try:
        # Run transcription in thread pool (it's blocking)
        loop = asyncio.get_event_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(
                audio_path,
                beam_size=5,
                best_of=5,
                vad_filter=True,  # Filter out silence
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=400
                )
            )
        )
        
        # Collect segments and build full text
        segment_list = []
        full_text_parts = []
        total_confidence = 0.0
        segment_count = 0
        
        for segment in segments:
            segment_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "avg_logprob": segment.avg_logprob
            })
            full_text_parts.append(segment.text.strip())
            # Convert log probability to rough confidence score
            # Higher (less negative) = more confident
            total_confidence += min(1.0, max(0.0, 1.0 + segment.avg_logprob))
            segment_count += 1
        
        avg_confidence = total_confidence / segment_count if segment_count > 0 else 0.0
        
        return {
            "text": " ".join(full_text_parts),
            "language": info.language,
            "language_probability": info.language_probability,
            "segments": segment_list,
            "confidence": avg_confidence,
            "duration": info.duration
        }
        
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return {
            "text": "",
            "language": None,
            "segments": [],
            "confidence": 0.0,
            "error": str(e)
        }

async def transcribe_pending_chunks():
    """
    Background worker to transcribe pending audio chunks.
    Called periodically to process uploaded audio.
    """
    from . import database as db
    
    pending = await db.get_pending_chunks()
    
    for chunk in pending:
        logger.info(f"Transcribing chunk {chunk['id']} from {chunk['file_path']}")
        
        result = await transcribe_audio(chunk['file_path'])
        
        if result.get('error'):
            logger.error(f"Failed to transcribe chunk {chunk['id']}: {result['error']}")
            continue
        
        if result['text']:
            await db.save_transcript(
                chunk_id=chunk['id'],
                session_id=chunk['session_id'],
                user_id=chunk['user_id'],
                text=result['text'],
                language=result.get('language'),
                confidence=result.get('confidence')
            )
            logger.info(f"✅ Transcribed chunk {chunk['id']}: {result['text'][:50]}...")

# Simple health check
def is_whisper_available() -> bool:
    """Check if Whisper is available."""
    return WHISPER_AVAILABLE
