"""
InstaBio Streaming Transcription — WebSocket endpoint
Receives raw audio chunks over WebSocket, runs faster-whisper in streaming mode,
and returns partial transcript text as it's produced.

Usage:
    WebSocket /ws/transcribe
    Client sends: binary audio frames (2-3s chunks of webm/opus)
    Server sends: JSON { "text": "...", "final": false, "language": "en" }
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def handle_streaming_transcription(websocket):
    """
    WebSocket handler for streaming transcription.
    Client sends audio chunks as binary messages.
    Server transcribes each chunk and sends partial results.
    """
    from .transcription import is_whisper_available, transcribe_audio

    if not is_whisper_available():
        await websocket.send_json({
            "text": "",
            "final": False,
            "error": "Transcription engine not available — words will appear after upload",
            "language": None
        })
        # Keep connection alive but non-functional
        try:
            while True:
                await websocket.receive_bytes()
                await websocket.send_json({
                    "text": "",
                    "final": False,
                    "status": "buffering"
                })
        except Exception:
            return

    # Whisper is available — process chunks
    temp_dir = tempfile.mkdtemp(prefix="instabio_stream_")
    chunk_counter = 0
    detected_language = None
    buffer_bytes = bytearray()

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=120)
            except asyncio.TimeoutError:
                await websocket.send_json({"text": "", "final": False, "status": "timeout"})
                break

            buffer_bytes.extend(data)
            chunk_counter += 1

            # Process every 2 chunks (~4-6 seconds of audio) for responsiveness
            if chunk_counter % 2 == 0 or len(buffer_bytes) > 100000:
                temp_path = os.path.join(temp_dir, f"stream_{chunk_counter}.webm")
                with open(temp_path, 'wb') as f:
                    f.write(buffer_bytes)

                result = await transcribe_audio(temp_path)
                text = result.get("text", "")
                lang = result.get("language")
                if lang:
                    detected_language = lang

                await websocket.send_json({
                    "text": text,
                    "final": False,
                    "language": detected_language,
                    "chunk": chunk_counter
                })

                # Clean up temp file and reset buffer
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                buffer_bytes = bytearray()

    except Exception as e:
        logger.error(f"Streaming transcription error: {e}")
        try:
            await websocket.send_json({"text": "", "final": True, "error": str(e)})
        except Exception:
            pass
    finally:
        # Clean up temp directory
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def get_transcription_status() -> dict:
    """Return transcription engine availability for R2.2 hardware detection UI."""
    from .transcription import is_whisper_available
    available = is_whisper_available()
    model_size = os.environ.get("WHISPER_MODEL", "base")
    return {
        "available": available,
        "engine": "faster-whisper" if available else None,
        "model": model_size if available else None,
        "status": "ready" if available else "unavailable",
        "message": (
            f"🟢 Transcription ready ({model_size} model)"
            if available
            else "📝 Transcription will happen after upload"
        )
    }
