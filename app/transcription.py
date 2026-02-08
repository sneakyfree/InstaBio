"""
InstaBio Transcription Module
Uses the existing Faster Whisper installation at /opt/whisper-stt/
"""

import asyncio
import subprocess
import json
import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Path to the existing whisper transcription script
WHISPER_SCRIPT = "/opt/whisper-stt/transcribe.sh"
WHISPER_AVAILABLE = os.path.exists(WHISPER_SCRIPT)

async def transcribe_audio(audio_path: str, model: str = "base") -> dict:
    """
    Transcribe an audio file using the existing Faster Whisper installation.
    
    Args:
        audio_path: Path to the audio file
        model: Whisper model size (tiny, base, small, medium, large)
        
    Returns:
        dict with 'text', 'language', 'duration', 'confidence', and 'error' (if any)
    """
    if not WHISPER_AVAILABLE:
        logger.warning(f"Whisper script not found at {WHISPER_SCRIPT}")
        return {
            "text": "[Transcription unavailable - Whisper not installed]",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": "Whisper not available on this system"
        }
    
    if not os.path.exists(audio_path):
        return {
            "text": "",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": f"Audio file not found: {audio_path}"
        }
    
    try:
        # Run transcription in a subprocess
        # Using run_in_executor since subprocess is blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [WHISPER_SCRIPT, audio_path, f"--model={model}", "--json"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            logger.error(f"Transcription failed: {error_msg}")
            return {
                "text": "",
                "language": None,
                "duration": 0,
                "confidence": 0.0,
                "error": error_msg
            }
        
        # Parse JSON output
        try:
            data = json.loads(result.stdout.strip())
            
            # The script returns: text, engine, model, language, duration, elapsed_seconds
            text = data.get("text", "").strip()
            language = data.get("language")
            duration = data.get("duration", 0)
            elapsed = data.get("elapsed_seconds", 0)
            
            # Calculate a rough confidence score (faster = likely clearer audio)
            # This is a heuristic since the script doesn't return confidence
            confidence = 0.85 if text else 0.0
            if duration > 0 and elapsed > 0:
                # If transcription took much longer than audio, might be harder audio
                ratio = elapsed / duration
                if ratio < 1:
                    confidence = 0.95
                elif ratio > 3:
                    confidence = 0.7
            
            logger.info(f"Transcribed {audio_path}: {len(text)} chars, {language}, {duration}s audio in {elapsed}s")
            
            return {
                "text": text,
                "language": language,
                "duration": duration,
                "confidence": confidence,
                "elapsed_seconds": elapsed,
                "engine": data.get("engine", "faster-whisper"),
                "model": data.get("model", model)
            }
            
        except json.JSONDecodeError as e:
            # If JSON parsing fails, maybe it returned plain text
            text = result.stdout.strip()
            logger.warning(f"JSON parse failed, using raw output: {e}")
            return {
                "text": text,
                "language": None,
                "duration": 0,
                "confidence": 0.75,
                "error": None
            }
            
    except subprocess.TimeoutExpired:
        logger.error(f"Transcription timed out for {audio_path}")
        return {
            "text": "",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": "Transcription timed out"
        }
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return {
            "text": "",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": str(e)
        }

async def transcribe_pending_chunks():
    """
    Background worker to transcribe pending audio chunks.
    Called periodically to process uploaded audio.
    Finds all unprocessed chunks from the DB, transcribes them, and stores results.
    """
    from . import database as db
    
    pending = await db.get_pending_chunks()
    
    if not pending:
        return
    
    logger.info(f"Found {len(pending)} pending chunks to transcribe")
    
    for chunk in pending:
        chunk_id = chunk['id']
        file_path = chunk['file_path']
        session_id = chunk['session_id']
        user_id = chunk['user_id']
        
        logger.info(f"Transcribing chunk {chunk_id} from {file_path}")
        
        # Check if file exists
        if not os.path.exists(file_path):
            logger.warning(f"Audio file not found for chunk {chunk_id}: {file_path}")
            await db.mark_chunk_failed(chunk_id, "File not found")
            continue
        
        # Validate audio file before wasting CPU on transcription
        try:
            validation = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file_path],
                capture_output=True, text=True, timeout=10
            )
            if validation.returncode != 0:
                error = validation.stderr.strip()[:200] if validation.stderr else "Invalid audio file"
                logger.warning(f"Invalid audio file for chunk {chunk_id}: {error}")
                await db.mark_chunk_failed(chunk_id, f"Invalid audio: {error}")
                continue
        except Exception as e:
            logger.warning(f"Audio validation error for chunk {chunk_id}: {e}")
            await db.mark_chunk_failed(chunk_id, f"Validation error: {e}")
            continue
        
        # Transcribe
        result = await transcribe_audio(file_path)
        
        if result.get('error'):
            logger.error(f"Failed to transcribe chunk {chunk_id}: {result['error']}")
            # Mark as failed with retry count — stop after 3 attempts
            await db.mark_chunk_failed(chunk_id, result['error'])
            continue
        
        if result['text']:
            # Save transcript to database
            await db.save_transcript(
                chunk_id=chunk_id,
                session_id=session_id,
                user_id=user_id,
                text=result['text'],
                language=result.get('language'),
                confidence=result.get('confidence')
            )
            logger.info(f"✅ Transcribed chunk {chunk_id}: {result['text'][:80]}...")
        else:
            logger.warning(f"Chunk {chunk_id} transcribed but returned empty text")

def is_whisper_available() -> bool:
    """Check if Whisper transcription is available on this system."""
    return WHISPER_AVAILABLE
