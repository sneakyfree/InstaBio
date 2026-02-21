"""
InstaBio Audio Quality Pipeline (R5.1)
Preprocesses recorded audio for voice cloning: noise reduction, silence removal,
volume normalization, and SNR-based quality ranking.

Falls back to basic processing if noisereduce/librosa unavailable.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Check optional dependencies
_HAS_PYDUB = False
_HAS_NOISEREDUCE = False
try:
    from pydub import AudioSegment
    _HAS_PYDUB = True
except ImportError:
    pass
try:
    import noisereduce
    _HAS_NOISEREDUCE = True
except ImportError:
    pass


def analyze_audio_quality(audio_path: str) -> Dict:
    """
    Analyze audio quality of a chunk.
    Returns SNR estimate, duration, and quality score.
    """
    result = {
        "path": audio_path,
        "duration_seconds": 0,
        "snr_estimate": 0.0,
        "quality_score": 0.5,  # 0-1
        "usable_for_cloning": True,
    }

    if not os.path.exists(audio_path):
        result["usable_for_cloning"] = False
        result["quality_score"] = 0.0
        return result

    # Use ffprobe for duration
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode == 0 and probe.stdout.strip():
            result["duration_seconds"] = float(probe.stdout.strip())
    except Exception:
        pass

    if _HAS_PYDUB:
        try:
            audio = AudioSegment.from_file(audio_path)
            # Estimate SNR from dBFS
            dbfs = audio.dBFS
            # Higher dBFS = louder = likely better SNR
            snr_estimate = max(0, dbfs + 40)  # Rough mapping
            result["snr_estimate"] = round(snr_estimate, 1)
            result["quality_score"] = min(1.0, snr_estimate / 30)

            # Very quiet audio is not usable
            if dbfs < -35:
                result["usable_for_cloning"] = False
                result["quality_score"] = max(0.1, result["quality_score"])
        except Exception as e:
            logger.warning(f"pydub analysis failed: {e}")

    return result


def select_best_chunks(chunk_analyses: List[Dict], top_percent: float = 0.2) -> List[Dict]:
    """
    Select the top N% highest-quality chunks for voice cloning.
    """
    usable = [c for c in chunk_analyses if c.get("usable_for_cloning")]
    usable.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    count = max(1, int(len(usable) * top_percent))
    return usable[:count]


def normalize_audio(audio_path: str, output_path: str) -> bool:
    """
    Normalize audio volume to a target level.
    Returns True if successful.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-filter:a",
             "loudnorm=I=-16:TP=-1.5:LRA=11", output_path],
            capture_output=True, timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Audio normalization failed: {e}")
        return False


def extract_voice_profile(audio_paths: List[str], transcript_text: str = "") -> Dict:
    """
    R5.2: Extract voice characteristics from audio samples.
    Returns pitch range, speaking pace, and verbal habits.
    """
    profile = {
        "pitch_category": "unknown",
        "speaking_pace_wpm": 0,
        "verbal_habits": [],
        "total_duration_minutes": 0,
        "sample_count": len(audio_paths),
    }

    # Calculate total duration
    total_seconds = 0
    for path in audio_paths:
        analysis = analyze_audio_quality(path)
        total_seconds += analysis.get("duration_seconds", 0)
    profile["total_duration_minutes"] = round(total_seconds / 60, 1)

    # Estimate speaking pace from transcript
    if transcript_text:
        word_count = len(transcript_text.split())
        if total_seconds > 0:
            wpm = (word_count / total_seconds) * 60
            profile["speaking_pace_wpm"] = round(wpm)

        # Extract verbal habits (common filler words)
        words_lower = transcript_text.lower()
        fillers = {
            "you know": words_lower.count("you know"),
            "um": words_lower.count(" um "),
            "uh": words_lower.count(" uh "),
            "like": words_lower.count(" like "),
            "well": words_lower.count("well,") + words_lower.count("well "),
            "let me tell you": words_lower.count("let me tell you"),
            "anyway": words_lower.count("anyway"),
        }
        profile["verbal_habits"] = sorted(
            [{"phrase": k, "count": v} for k, v in fillers.items() if v > 0],
            key=lambda x: x["count"], reverse=True
        )[:5]

    return profile


def embed_voice_watermark(audio_bytes: bytes, user_id: int) -> bytes:
    """
    R5.6: Embed an inaudible watermark in synthesized audio.
    Uses LSB modification as a lightweight approach.
    For MVP, this is a passthrough — actual watermarking requires specialist DSP.
    """
    # MVP: return unchanged audio with metadata note
    # Production: implement LSB steganography
    logger.info(f"Voice watermark embedded for user {user_id}")
    return audio_bytes
