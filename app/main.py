"""
InstaBio - Main FastAPI Application
Phase 1: The Seed - Recording MVP

Your story. Forever.
"""

import os
import html as html_mod
import uuid
import secrets
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from . import database as db
from .transcription import transcribe_audio, transcribe_pending_chunks, is_whisper_available
from .entity_extraction import get_extractor, ExtractionResult, build_timeline
from .biography import get_biography_generator, BiographyStyle
from .journal import get_journal_generator
from .llm_client import get_llm_client, test_connection
from .voice_clone import get_voice_clone_status_dict
from .avatar import get_avatar_status_dict, count_user_photos, list_user_photos, save_user_photo, PHOTOS_DIR
from .avatar_video import generate_avatar_video, list_portraits as list_avatar_portraits, get_portrait as get_avatar_portrait, check_veron_available
from .interview import start_session as start_interview_session, next_question as interview_next_question, get_session_status as get_interview_status
from .soul import get_soul_status_dict

# ----- Logging Configuration -----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("instabio")

# ----- Rate Limiter -----
limiter = Limiter(key_func=get_remote_address)

# ----- Configuration -----
BASE_DIR = Path(__file__).parent.parent
AUDIO_DIR = BASE_DIR / "data" / "audio"
PHOTOS_DIR_DATA = BASE_DIR / "data" / "photos"
STATIC_DIR = BASE_DIR / "static"

# Ensure directories exist
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
PHOTOS_DIR_DATA.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# ----- Lifespan Events -----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    print("\n🌱 InstaBio starting up...")
    await db.init_db()
    
    # Start background transcription worker
    transcription_task = asyncio.create_task(transcription_worker())
    
    print("✅ InstaBio ready!")
    print(f"   Whisper available: {is_whisper_available()}")
    print(f"   Audio storage: {AUDIO_DIR}")
    print("")
    
    yield
    
    # Shutdown
    transcription_task.cancel()
    print("\n👋 InstaBio shutting down...")

async def transcription_worker():
    """Background worker that processes pending transcriptions."""
    while True:
        try:
            await transcribe_pending_chunks()
        except Exception as e:
            print(f"Transcription worker error: {e}")
        await asyncio.sleep(10)  # Check every 10 seconds

# ----- App Setup -----
app = FastAPI(
    title="InstaBio",
    description="Your story. Forever. — AI-powered life memoir platform",
    version="0.1.0",
    lifespan=lifespan
)

# Rate limiter setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----- Request/Response Models -----

class RegisterRequest(BaseModel):
    first_name: str
    birth_year: int
    email: EmailStr

class RegisterResponse(BaseModel):
    success: bool
    token: str
    user_id: int
    first_name: str
    message: str

class SessionResponse(BaseModel):
    id: int
    session_uuid: str
    started_at: str
    total_duration_seconds: float
    chunk_count: int
    status: str

class TranscriptResponse(BaseModel):
    id: int
    text: str
    session_uuid: str
    created_at: str
    language: Optional[str]
    confidence: Optional[float]

# ----- Helper Functions -----

async def get_current_user(authorization: str = Header(None)) -> dict:
    """Get current user from authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Extract token (format: "Bearer <token>" or just "<token>")
    token = authorization.replace("Bearer ", "").strip()
    
    user = await db.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Check token expiration (90 days)
    TOKEN_EXPIRY_DAYS = int(os.environ.get("TOKEN_EXPIRY_DAYS", "90"))
    token_created = user.get("token_created_at", "")
    if token_created:
        try:
            created = datetime.fromisoformat(token_created)
            from datetime import timedelta
            if datetime.utcnow() - created > timedelta(days=TOKEN_EXPIRY_DAYS):
                raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        except ValueError:
            pass  # Malformed date — allow through, will be fixed on next login
    
    return user

# ----- API Endpoints -----

@app.get("/")
async def root():
    """Serve the landing page."""
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/onboard")
async def onboard():
    """Serve the onboarding page."""
    return FileResponse(STATIC_DIR / "onboard.html")

@app.get("/record")
async def record():
    """Serve the recording page."""
    return FileResponse(STATIC_DIR / "record.html")

@app.get("/vault")
async def vault():
    """Serve the vault page."""
    return FileResponse(STATIC_DIR / "vault.html")

@app.get("/biography")
async def biography_page():
    """Serve the biography viewer page."""
    return FileResponse(STATIC_DIR / "biography.html")

@app.get("/journal")
async def journal_page():
    """Serve the journal viewer page."""
    return FileResponse(STATIC_DIR / "journal.html")

@app.get("/progress")
async def progress_page():
    """Serve the progress dashboard page."""
    return FileResponse(STATIC_DIR / "progress.html")

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "whisper_available": is_whisper_available(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/register", response_model=RegisterResponse)
@limiter.limit("5/minute")
async def register(data: RegisterRequest, request: Request):
    """
    Register a new user.
    For MVP: simple name + email, no password required.
    Returns a session token for subsequent requests.
    Rate limited to 5 requests per minute per IP.
    """
    logger.info(f"Registration attempt for email: {data.email}")
    
    # Check if email already exists
    existing = await db.get_user_by_email(data.email)
    if existing:
        # For MVP, just return existing user's token
        # In production, send magic link email
        return RegisterResponse(
            success=True,
            token=existing['session_token'],
            user_id=existing['id'],
            first_name=existing['first_name'],
            message="Welcome back! We found your account."
        )
    
    # Generate secure session token
    token = secrets.token_urlsafe(32)
    
    # Create user
    try:
        user_id = await db.create_user(
            first_name=data.first_name,
            birth_year=data.birth_year,
            email=data.email,
            session_token=token
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")
    
    return RegisterResponse(
        success=True,
        token=token,
        user_id=user_id,
        first_name=data.first_name,
        message=f"Welcome, {data.first_name}! Your story begins now."
    )

@app.post("/api/logout")
async def logout(authorization: str = Header(None)):
    """
    Log out the current user by invalidating their session token.
    The frontend should clear localStorage after calling this.
    """
    user = await get_current_user(authorization)
    await db.invalidate_token(user['id'])
    return {
        "success": True,
        "message": "Logged out successfully."
    }

@app.post("/api/session/start")
async def start_session(authorization: str = Header(None)):
    """
    Start a new recording session.
    Returns a session UUID for uploading chunks.
    """
    user = await get_current_user(authorization)
    
    session_uuid = str(uuid.uuid4())
    session_id = await db.create_recording_session(user['id'], session_uuid)
    
    # Create directory for this session's audio
    session_audio_dir = AUDIO_DIR / session_uuid
    session_audio_dir.mkdir(parents=True, exist_ok=True)
    
    return {
        "success": True,
        "session_uuid": session_uuid,
        "session_id": session_id,
        "message": "Recording session started. We're listening."
    }

@app.post("/api/upload")
async def upload_chunk(
    audio: UploadFile = File(...),
    session_uuid: str = Form(...),
    chunk_index: int = Form(...),
    duration: float = Form(0.0),
    authorization: str = Header(None)
):
    """
    Upload an audio chunk.
    Chunks are saved locally and queued for transcription.
    """
    user = await get_current_user(authorization)
    
    # Verify session belongs to user
    session = await db.get_session_by_uuid(session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session['user_id'] != user['id']:
        raise HTTPException(status_code=403, detail="Session does not belong to you")
    
    # Save audio file
    session_audio_dir = AUDIO_DIR / session_uuid
    session_audio_dir.mkdir(parents=True, exist_ok=True)
    
    # Use webm extension since that's what MediaRecorder produces
    filename = f"chunk_{chunk_index:05d}.webm"
    file_path = session_audio_dir / filename
    
    # Write file
    content = await audio.read()
    
    # Basic validation: must be at least 1KB and start with WebM/Matroska magic bytes
    if len(content) < 1024:
        raise HTTPException(status_code=400, detail="Audio file too small — may be corrupt")
    # WebM files start with 0x1A45DFA3 (EBML header)
    if content[:4] != b'\x1a\x45\xdf\xa3':
        raise HTTPException(status_code=400, detail="Invalid audio format — expected WebM")
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Save to database
    chunk_id = await db.save_audio_chunk(
        session_id=session['id'],
        chunk_index=chunk_index,
        file_path=str(file_path),
        duration=duration
    )
    
    return {
        "success": True,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "message": "Chunk saved and queued for transcription"
    }

@app.get("/api/sessions")
async def get_sessions(authorization: str = Header(None)):
    """
    Get all recording sessions for the current user.
    """
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    
    return {
        "success": True,
        "sessions": sessions,
        "total_count": len(sessions)
    }

@app.get("/api/transcripts")
async def get_transcripts(
    search: Optional[str] = None,
    authorization: str = Header(None)
):
    """
    Get all transcripts for the current user.
    Optionally filter by search query.
    """
    user = await get_current_user(authorization)
    transcripts = await db.get_user_transcripts(user['id'], search)
    
    # Escape transcript text for safe rendering (B6 defense-in-depth)
    for t in transcripts:
        if 'text' in t:
            t['text'] = html_mod.escape(t['text'])
    
    # Calculate total words
    total_words = sum(len(t['text'].split()) for t in transcripts)
    
    return {
        "success": True,
        "transcripts": transcripts,
        "total_count": len(transcripts),
        "total_words": total_words
    }

@app.get("/api/user/stats")
async def get_user_stats(authorization: str = Header(None)):
    """
    Get statistics for the current user.
    """
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    transcripts = await db.get_user_transcripts(user['id'])
    
    total_duration = sum(s['total_duration_seconds'] for s in sessions)
    total_words = sum(len(t['text'].split()) for t in transcripts)
    
    return {
        "success": True,
        "first_name": user['first_name'],
        "birth_year": user['birth_year'],
        "total_sessions": len(sessions),
        "total_duration_seconds": total_duration,
        "total_duration_formatted": format_duration(total_duration),
        "total_chunks": sum(s['chunk_count'] for s in sessions),
        "total_transcripts": len(transcripts),
        "total_words": total_words
    }

def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

# ----- Voice Clone, Avatar, Soul Status Endpoints -----

@app.get("/api/voice-clone/status")
async def get_voice_clone_status(authorization: str = Header(None)):
    """Get voice clone quality status for the current user."""
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    
    # Calculate total recording hours
    total_seconds = sum(s['total_duration_seconds'] for s in sessions)
    total_hours = total_seconds / 3600
    
    status = get_voice_clone_status_dict(total_hours)
    return {"success": True, **status}


@app.get("/api/avatar/status")
async def get_avatar_status(authorization: str = Header(None)):
    """Get avatar readiness status for the current user."""
    user = await get_current_user(authorization)
    
    # Get photo count
    photos_count = await count_user_photos(user['id'])
    
    # Get video hours (recordings marked as video)
    # For now, we don't have video marking yet, so default to 0
    video_hours = await db.get_user_video_hours(user['id']) if hasattr(db, 'get_user_video_hours') else 0.0
    
    status = get_avatar_status_dict(photos_count, video_hours)
    return {"success": True, **status}


@app.get("/api/soul/status")
async def get_soul_status(authorization: str = Header(None)):
    """Get Soul readiness status for the current user."""
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    
    # Calculate total recording hours
    total_seconds = sum(s['total_duration_seconds'] for s in sessions)
    total_hours = total_seconds / 3600
    
    # Get photo count for avatar status
    photos_count = await count_user_photos(user['id'])
    
    # Voice clone is ready if we have 1+ hours
    voice_clone_ready = total_hours >= 1.0
    
    # Avatar is ready if we have photos
    avatar_ready = photos_count >= 1
    
    # Biography status (placeholder - would come from biography module)
    biography_status = 'none'
    biography_chapters_ready = 0
    biography_chapters_total = 5
    
    # Check if we have enough recordings to generate biography
    if total_hours >= 2:
        biography_status = 'processing'
        biography_chapters_ready = min(int(total_hours / 2), 5)
    if total_hours >= 10 and biography_chapters_ready >= 5:
        biography_status = 'ready'
    
    status = get_soul_status_dict(
        recording_hours=total_hours,
        biography_status=biography_status,
        biography_chapters_ready=biography_chapters_ready,
        biography_chapters_total=biography_chapters_total,
        voice_clone_ready=voice_clone_ready,
        avatar_ready=avatar_ready,
    )
    return {"success": True, **status}


@app.get("/api/products/status")
async def get_products_status(authorization: str = Header(None)):
    """Get unified status overview of all 5 InstaBio products."""
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    transcripts = await db.get_user_transcripts(user['id'])
    
    # Recording stats
    total_seconds = sum(s['total_duration_seconds'] for s in sessions)
    total_hours = total_seconds / 3600
    
    # Photo count
    photos_count = await count_user_photos(user['id'])
    
    # Video hours (placeholder)
    video_hours = 0.0
    
    # Voice clone status
    voice_status = get_voice_clone_status_dict(total_hours)
    
    # Avatar status
    avatar_status = get_avatar_status_dict(photos_count, video_hours)
    
    # Biography status (placeholder logic)
    biography_status = 'none'
    biography_chapters_ready = 0
    biography_chapters_total = 5
    if total_hours >= 2:
        biography_status = 'processing'
        biography_chapters_ready = min(int(total_hours / 2), 5)
    if total_hours >= 10:
        biography_status = 'ready'
        biography_chapters_ready = 5
    
    # Journal entries (estimate from transcripts)
    journal_entries = len(transcripts)
    journal_status = 'ready' if journal_entries > 0 else 'none'
    
    # Soul status
    voice_clone_ready = total_hours >= 1.0
    avatar_ready = photos_count >= 1
    soul_status = get_soul_status_dict(
        recording_hours=total_hours,
        biography_status=biography_status,
        biography_chapters_ready=biography_chapters_ready,
        biography_chapters_total=biography_chapters_total,
        voice_clone_ready=voice_clone_ready,
        avatar_ready=avatar_ready,
    )
    
    return {
        "success": True,
        "user": {
            "first_name": user['first_name'],
            "birth_year": user['birth_year'],
        },
        "recording": {
            "hours": round(total_hours, 2),
            "sessions": len(sessions),
            "total_chunks": sum(s['chunk_count'] for s in sessions),
        },
        "biography": {
            "status": biography_status,
            "chapters_ready": biography_chapters_ready,
            "chapters_total": biography_chapters_total,
        },
        "journal": {
            "status": journal_status,
            "entries": journal_entries,
        },
        "voice_clone": {
            "tier": voice_status['tier'],
            "tier_name": voice_status['tier_name'],
            "quality_pct": voice_status['quality_pct'],
            "hours_to_next_tier": voice_status['hours_to_next_tier'],
            "is_ready": voice_status['is_ready'],
        },
        "avatar": {
            "tier": avatar_status['tier'],
            "tier_name": avatar_status['tier_name'],
            "quality_pct": avatar_status['quality_pct'],
            "photos": avatar_status['photos_uploaded'],
            "is_ready": avatar_status['is_ready'],
        },
        "soul": {
            "readiness_pct": soul_status['readiness_pct'],
            "tier": soul_status['tier'],
            "requirements_met": soul_status['requirements_met'],
            "is_ready": soul_status['is_ready'],
            "next_step": soul_status['next_step'],
        },
    }


# ----- Photo Upload Endpoints -----

@app.post("/api/photo/upload")
async def upload_photo(
    photo: UploadFile = File(...),
    authorization: str = Header(None)
):
    """Upload a photo for avatar creation."""
    user = await get_current_user(authorization)
    
    # Validate file type
    allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/heic'}
    if photo.content_type and photo.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP, and HEIC images are allowed")
    
    # Read and save photo
    content = await photo.read()
    
    # Limit file size (10MB)
    max_size = 10 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="Photo too large. Maximum size is 10MB")
    
    result = await save_user_photo(user['id'], photo.filename or "photo.jpg", content)
    
    # Get updated photo count
    photos_count = await count_user_photos(user['id'])
    
    return {
        "success": True,
        "message": f"Photo uploaded! You now have {photos_count} photo(s).",
        "photo": result,
        "total_photos": photos_count,
    }


@app.get("/api/photos")
async def get_photos(authorization: str = Header(None)):
    """List all photos for the current user."""
    user = await get_current_user(authorization)
    
    photos = await list_user_photos(user['id'])
    
    return {
        "success": True,
        "photos": photos,
        "total_count": len(photos),
    }


@app.get("/api/photos/{user_id}/{filename}")
async def serve_photo(user_id: int, filename: str, authorization: str = Header(None)):
    """Serve a user's photo."""
    user = await get_current_user(authorization)
    
    # Security: only allow users to access their own photos
    if user['id'] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    file_path = PHOTOS_DIR / str(user_id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Photo not found")
    
    return FileResponse(file_path)


@app.post("/api/recording/video")
async def mark_recording_video(
    session_uuid: str = Form(...),
    is_video: bool = Form(True),
    authorization: str = Header(None)
):
    """Mark a recording session as video (face on camera)."""
    user = await get_current_user(authorization)
    
    # Verify session belongs to user
    session = await db.get_session_by_uuid(session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session['user_id'] != user['id']:
        raise HTTPException(status_code=403, detail="Session does not belong to you")
    
    # Update session (would need database schema update)
    # For now, just acknowledge
    return {
        "success": True,
        "message": f"Session marked as {'video' if is_video else 'audio only'}",
        "session_uuid": session_uuid,
        "is_video": is_video,
    }


# ----- Story Processing API -----

# In-memory caches for generated content (persisted to DB in G10)
_entities_cache: dict = {}
_timeline_cache: dict = {}
_biography_cache: dict = {}
_journal_cache: dict = {}

@app.post("/api/process")
async def trigger_processing(
    background_tasks: BackgroundTasks,
    authorization: str = Header(None)
):
    """
    Trigger the processing pipeline for a user's transcripts.
    Runs entity extraction, biography, and journal generation in background.
    """
    user = await get_current_user(authorization)
    user_id = user['id']
    
    # Check if already processing
    existing = await db.get_processing_status(user_id)
    if existing and existing.get("status") == "processing":
        return {
            "success": True,
            "status": "already_processing",
            "message": "Your story is already being processed."
        }
    
    # Start processing in background
    await db.upsert_processing_status(
        user_id=user_id,
        status="processing",
        stage="starting",
        progress=0,
        started_at=datetime.utcnow().isoformat()
    )
    
    background_tasks.add_task(run_processing_pipeline, user_id, user['first_name'])
    
    return {
        "success": True,
        "status": "started",
        "message": "Processing started. Check /api/progress for updates."
    }

async def run_processing_pipeline(user_id: int, user_name: str):
    """Run the full processing pipeline for a user."""
    try:
        # Stage 1: Get transcripts
        await db.upsert_processing_status(user_id, "processing", "fetching_transcripts", 10)
        
        transcripts = await db.get_user_transcripts(user_id)
        
        if not transcripts:
            await db.upsert_processing_status(
                user_id, "complete", "no_transcripts", 100,
                completed_at=datetime.utcnow().isoformat()
            )
            return
        
        # Stage 2: Entity extraction
        await db.upsert_processing_status(user_id, "processing", "extracting_entities", 20)
        
        extractor = get_extractor()
        extraction_results = []
        
        for i, t in enumerate(transcripts):
            result = await extractor.extract(
                transcript=t['text'],
                session_id=t.get('session_uuid')
            )
            extraction_results.append(result)
            progress = 20 + int((i / len(transcripts)) * 20)
            await db.upsert_processing_status(user_id, "processing", "extracting_entities", progress)
        
        # Merge all extractions
        merged_extraction = extractor.merge_results(extraction_results)
        _entities_cache[user_id] = merged_extraction.to_dict()
        
        # Stage 3: Build timeline
        await db.upsert_processing_status(user_id, "processing", "building_timeline", 45)
        
        timeline = await build_timeline(merged_extraction.events, merged_extraction.dates)
        _timeline_cache[user_id] = timeline
        
        # Stage 4: Generate biography
        await db.upsert_processing_status(user_id, "processing", "generating_biography", 55)
        
        bio_generator = get_biography_generator()
        transcript_dicts = [{"text": t['text'], "session_id": t.get('session_uuid')} for t in transcripts]
        
        biography = await bio_generator.generate_biography(
            user_name=user_name,
            transcripts=transcript_dicts,
            extraction=merged_extraction,
            timeline=timeline,
            style=BiographyStyle.POLISHED
        )
        _biography_cache[user_id] = biography.to_dict()
        
        await db.upsert_processing_status(user_id, "processing", "generating_biography", 75)
        
        # Stage 5: Generate journal
        await db.upsert_processing_status(user_id, "processing", "generating_journal", 80)
        
        journal_generator = get_journal_generator()
        journal = await journal_generator.generate_journal(
            user_name=user_name,
            extraction=merged_extraction,
            timeline=timeline,
            transcripts=transcript_dicts
        )
        _journal_cache[user_id] = journal.to_dict()
        
        # Complete
        await db.upsert_processing_status(
            user_id, "complete", "complete", 100,
            completed_at=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        await db.upsert_processing_status(
            user_id, "error", "error", 0,
            error=str(e)
        )

@app.get("/api/progress")
async def get_progress(authorization: str = Header(None)):
    """Get processing progress for the current user."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    status = await db.get_processing_status(user_id)
    if not status:
        return {
            "success": True,
            "status": "not_started",
            "progress": 0,
            "stage": "not_started",
            "message": "No processing started yet. Use POST /api/process to begin."
        }
    
    return {
        "success": True,
        "status": status["status"],
        "progress": status["progress"],
        "stage": status["stage"],
    }

@app.get("/api/entities")
async def get_entities(authorization: str = Header(None)):
    """Get extracted entities for the current user."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _entities_cache:
        return {
            "success": False,
            "message": "No entities extracted yet. Run POST /api/process first."
        }
    
    return {
        "success": True,
        "entities": _entities_cache[user_id]
    }

@app.get("/api/timeline")
async def get_timeline(authorization: str = Header(None)):
    """Get chronological timeline for the current user."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _timeline_cache:
        return {
            "success": False,
            "message": "No timeline generated yet. Run POST /api/process first."
        }
    
    return {
        "success": True,
        "timeline": _timeline_cache[user_id]
    }

@app.get("/api/biography")
async def get_biography(
    style: Optional[str] = None,
    authorization: str = Header(None)
):
    """Get generated biography for the current user."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    # Check processing status
    proc_status = await db.get_processing_status(user_id)
    if proc_status and proc_status.get("status") == "processing":
        return {
            "success": True,
            "status": "processing",
            "progress": proc_status.get("progress", 0),
            "stage": proc_status.get("stage", "unknown"),
            "message": "Your biography is being generated..."
        }
    
    if user_id not in _biography_cache:
        return {
            "success": False,
            "message": "No biography generated yet. Run POST /api/process first."
        }
    
    return {
        "success": True,
        "biography": _biography_cache[user_id]
    }

@app.get("/api/biography/chapter/{chapter_number}")
async def get_biography_chapter(
    chapter_number: int,
    authorization: str = Header(None)
):
    """Get a specific chapter from the biography."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _biography_cache:
        return {
            "success": False,
            "message": "No biography generated yet."
        }
    
    chapters = _biography_cache[user_id].get("chapters", [])
    
    for chapter in chapters:
        if chapter.get("number") == chapter_number:
            return {
                "success": True,
                "chapter": chapter
            }
    
    raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

@app.get("/api/journal")
async def get_journal(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    authorization: str = Header(None)
):
    """Get journal entries, optionally filtered by date range."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _journal_cache:
        return {
            "success": False,
            "message": "No journal generated yet. Run POST /api/process first."
        }
    
    journal = _journal_cache[user_id]
    entries = journal.get("entries", [])
    
    # Filter by date range if specified
    if start_date or end_date:
        from .journal import get_journal_generator
        jg = get_journal_generator()
        
        if start_date:
            start_key = jg._sort_key(start_date)
            entries = [e for e in entries if jg._sort_key(e["date"]) >= start_key]
        
        if end_date:
            end_key = jg._sort_key(end_date)
            entries = [e for e in entries if jg._sort_key(e["date"]) <= end_key]
    
    return {
        "success": True,
        "journal": {
            **journal,
            "entries": entries
        }
    }

@app.get("/api/journal/{date}")
async def get_journal_entry(
    date: str,
    authorization: str = Header(None)
):
    """Get a specific journal entry by date."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _journal_cache:
        return {
            "success": False,
            "message": "No journal generated yet."
        }
    
    entries = _journal_cache[user_id].get("entries", [])
    
    for entry in entries:
        if entry["date"].lower() == date.lower():
            return {
                "success": True,
                "entry": entry
            }
    
    raise HTTPException(status_code=404, detail=f"No entry found for date: {date}")

@app.get("/api/llm/status")
async def get_llm_status():
    """Check LLM (Ollama on Veron) availability."""
    available = await test_connection()
    
    return {
        "success": True,
        "available": available,
        "model": "qwen2.5:32b" if available else "mock",
        "message": "Veron 1 Ollama connected" if available else "Using mock responses (Veron unavailable)"
    }

# ----- Service Worker & Manifest -----

@app.get("/manifest.json")
async def manifest():
    """Serve PWA manifest."""
    return FileResponse(STATIC_DIR / "manifest.json")

@app.get("/sw.js")
async def service_worker():
    """Serve service worker."""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

# ----- Interview Mode Endpoints -----

class InterviewStartRequest(BaseModel):
    portrait_id: str = "default"

class InterviewNextRequest(BaseModel):
    session_id: str
    transcript: str
    portrait_id: str = "default"

@app.post("/api/interview/start")
async def api_interview_start(
    data: InterviewStartRequest,
    authorization: str = Header(None)
):
    """Start an interview session — returns opening question + avatar video URL."""
    user = await get_current_user(authorization)
    
    session = await start_interview_session(user['id'], user['first_name'])
    opening_question = session.questions_asked[0]['question']
    
    # Try to generate avatar video; None means use fallback
    video_url = await generate_avatar_video(opening_question, data.portrait_id)
    portrait = await get_avatar_portrait(data.portrait_id)
    
    return {
        "success": True,
        "session_id": session.session_id,
        "question": opening_question,
        "video_url": video_url,
        "portrait": portrait,
        "fallback": video_url is None,
    }

@app.post("/api/interview/next")
async def api_interview_next(
    data: InterviewNextRequest,
    authorization: str = Header(None)
):
    """Get next question based on transcript so far."""
    await get_current_user(authorization)
    
    question = await interview_next_question(data.session_id, data.transcript)
    video_url = await generate_avatar_video(question, data.portrait_id)
    
    return {
        "success": True,
        "question": question,
        "video_url": video_url,
        "fallback": video_url is None,
    }

@app.get("/api/interview/portraits")
async def api_interview_portraits(authorization: str = Header(None)):
    """List available interviewer portraits."""
    await get_current_user(authorization)
    portraits = await list_avatar_portraits()
    return {"success": True, "portraits": portraits}

@app.get("/api/interview/status/{session_id}")
async def api_interview_status(session_id: str, authorization: str = Header(None)):
    """Get interview session status."""
    await get_current_user(authorization)
    status = await get_interview_status(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return {"success": True, **status}


# ----- Error Handlers -----

@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors - serve index for SPA routing."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"}
        )
    return FileResponse(STATIC_DIR / "index.html")
