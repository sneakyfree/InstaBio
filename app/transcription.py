"""
InstaBio Transcription Module
Uses faster-whisper (Python package) for local, private, offline transcription.
No cloud, no external APIs. Your story stays on your machine.
"""

import asyncio
import subprocess
import os
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ---- Whisper availability check ----
def _check_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False

WHISPER_AVAILABLE = _check_faster_whisper()

# Lazy-loaded model (loaded once, reused)
_whisper_model = None
_whisper_model_size = os.environ.get("WHISPER_MODEL", "base")  # tiny/base/small/medium

def _get_model():
    """Load Whisper model once and cache it."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info(f"Loading Whisper model: {_whisper_model_size}")
        # CPU-only, int8 quantization for speed on laptop hardware
        _whisper_model = WhisperModel(
            _whisper_model_size,
            device="cpu",
            compute_type="int8"
        )
        logger.info("Whisper model loaded")
    return _whisper_model


def _run_transcription(audio_path: str) -> dict:
    """Synchronous transcription — runs in thread pool."""
    start = time.time()
    try:
        model = _get_model()
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            language=None,           # auto-detect
            vad_filter=True,         # skip silent parts
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text_parts = [seg.text for seg in segments]
        text = " ".join(text_parts).strip()
        elapsed = time.time() - start
        return {
            "text": text,
            "language": info.language if info else None,
            "duration": info.duration if info else 0,
            "confidence": 0.9 if text else 0.0,
            "elapsed_seconds": round(elapsed, 2),
            "engine": "faster-whisper",
            "model": _whisper_model_size,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return {
            "text": "",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": str(e),
        }


async def transcribe_audio(audio_path: str, model: str = None) -> dict:
    """
    Transcribe an audio file using faster-whisper.
    Runs in a thread pool to avoid blocking the event loop.
    """
    if not WHISPER_AVAILABLE:
        logger.warning("faster-whisper not installed. Run: pip install faster-whisper")
        return {
            "text": "[Transcription unavailable — Whisper not installed]",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": "faster-whisper not installed",
        }

    if not os.path.exists(audio_path):
        return {
            "text": "",
            "language": None,
            "duration": 0,
            "confidence": 0.0,
            "error": f"Audio file not found: {audio_path}",
        }

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_transcription, audio_path)
    return result


async def transcribe_pending_chunks():
    """
    Background worker — processes pending audio chunks from the DB.
    Called every 10 seconds from the transcription_worker loop.
    """
    from . import database as db

    pending = await db.get_pending_chunks()
    if not pending:
        return

    logger.info(f"Found {len(pending)} pending chunks to transcribe")

    for chunk in pending:
        chunk_id  = chunk['id']
        file_path = chunk['file_path']
        session_id = chunk['session_id']
        user_id    = chunk['user_id']

        logger.info(f"Transcribing chunk {chunk_id}: {file_path}")

        # File existence check
        if not os.path.exists(file_path):
            logger.warning(f"Audio file missing for chunk {chunk_id}")
            await db.mark_chunk_failed(chunk_id, "File not found")
            continue

        # Quick ffprobe validation
        try:
            val = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "json", file_path],
                capture_output=True, text=True, timeout=10
            )
            if val.returncode != 0:
                err = (val.stderr.strip()[:200] if val.stderr else "Invalid audio")
                await db.mark_chunk_failed(chunk_id, f"Invalid audio: {err}")
                continue
        except Exception as e:
            await db.mark_chunk_failed(chunk_id, f"Validation error: {e}")
            continue

        # Transcribe
        result = await transcribe_audio(file_path)

        if result.get('error'):
            logger.error(f"Chunk {chunk_id} transcription failed: {result['error']}")
            await db.mark_chunk_failed(chunk_id, result['error'])
            continue

        if result['text']:
            await db.save_transcript(
                chunk_id=chunk_id,
                session_id=session_id,
                user_id=user_id,
                text=result['text'],
                language=result.get('language'),
                confidence=result.get('confidence'),
            )
            logger.info(f"✅ Chunk {chunk_id} transcribed: {result['text'][:80]}...")
        else:
            logger.warning(f"Chunk {chunk_id}: empty transcription (silence?)")
            await db.mark_chunk_failed(chunk_id, "Empty transcription — no speech detected")


def is_whisper_available() -> bool:
    """Return True if faster-whisper is importable."""
    return WHISPER_AVAILABLE
