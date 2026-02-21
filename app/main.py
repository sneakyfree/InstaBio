"""
InstaBio - Main FastAPI Application
Phase 1: The Seed - Recording MVP

Your story. Forever.
"""

import os
import hashlib
import html as html_mod
import uuid
import secrets
import asyncio
import logging
from pathlib import Path
from datetime import datetime, UTC
from typing import Optional
from contextlib import asynccontextmanager
import aiosqlite
import bcrypt

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, BackgroundTasks, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from . import database as db
from .transcription import transcribe_audio, transcribe_pending_chunks, is_whisper_available
from .streaming_transcription import handle_streaming_transcription, get_transcription_status
from .entity_extraction import get_extractor, ExtractionResult, build_timeline
from .biography import get_biography_generator, BiographyStyle
from .journal import get_journal_generator
from .llm_client import get_llm_client, test_connection
from .voice_clone import get_voice_clone_status_dict, generate_voice_clone, synthesize_speech
from .avatar import get_avatar_status_dict, count_user_photos, list_user_photos, save_user_photo, generate_avatar, PHOTOS_DIR
from .avatar_video import generate_avatar_video, list_portraits as list_avatar_portraits, get_portrait as get_avatar_portrait, check_veron_available
from .interview import start_session as start_interview_session, next_question as interview_next_question, get_session_status as get_interview_status
from .soul import get_soul_status_dict, activate_soul, chat_with_soul
from .payments import create_checkout_session, handle_webhook as stripe_handle_webhook, list_products

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
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # SEC-5b: 50MB upload size limit
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
        except asyncio.CancelledError:
            logger.info("Transcription worker shutting down")
            break
        except (OSError, ConnectionError) as e:
            logger.warning(f"Transcription worker I/O error (will retry): {e}")
        except Exception as e:
            logger.error(f"Transcription worker unexpected error: {e}", exc_info=True)
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

# CORS — origins from env (comma-separated), falling back to safe localhost defaults
_default_origins = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000"
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# HTTPS redirect (enable in production with FORCE_HTTPS=1)
if os.environ.get("FORCE_HTTPS", "").strip() == "1":
    from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
    app.add_middleware(HTTPSRedirectMiddleware)

# R9: Security Headers Middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----- Request/Response Models -----

class RegisterRequest(BaseModel):
    first_name: str
    birth_year: int
    email: EmailStr
    pin: Optional[str] = None  # B2: optional 4-digit PIN
    is_signin: bool = False  # True when using Sign In form vs New Account

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
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            from datetime import timedelta
            if datetime.now(UTC) - created > timedelta(days=TOKEN_EXPIRY_DAYS):
                raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        except ValueError:
            raise HTTPException(status_code=401, detail="Session invalid. Please log in again.")  # SEC-10
    
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

@app.get("/pricing")
async def pricing_page():
    """R8.1: Serve the pricing/storefront page."""
    return FileResponse(STATIC_DIR / "pricing.html")

@app.get("/tv")
async def tv_page():
    """R6.4: Serve TV/Living Room mode."""
    return FileResponse(STATIC_DIR / "tv.html")

@app.get("/consent")
async def consent_page():
    """R10: Serve the privacy & consent portal."""
    return FileResponse(STATIC_DIR / "consent.html")

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "whisper_available": is_whisper_available(),
        "timestamp": datetime.now(UTC).isoformat()
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
    logger.info("Registration attempt")  # SEC-7: no PII in logs
    
    # Hash PIN if provided (B2) — uses bcrypt for secure hashing
    pin_hash = ''
    if data.pin and len(data.pin) == 4 and data.pin.isdigit():
        pin_hash = bcrypt.hashpw(data.pin.encode(), bcrypt.gensalt()).decode()
    
    existing = await db.get_user_by_email(data.email)
    if existing:
        # If this is a NEW ACCOUNT attempt (not sign-in), tell them to sign in
        if not data.is_signin:
            raise HTTPException(
                status_code=409,
                detail="An account already exists for that email! Please tap 'Sign In' to access your account."
            )
        # B2: Verify PIN if the account has one
        stored_pin = existing.get('pin_hash', '') or ''
        if stored_pin and data.pin:
            # Both have PIN — verify with bcrypt (+ SHA-256 migration)
            pin_ok = False
            try:
                pin_ok = bcrypt.checkpw(data.pin.encode(), stored_pin.encode())
            except (ValueError, TypeError) as exc:
                logger.warning(f"Invalid bcrypt hash format for user {existing.get('id')}: {exc}")
                pin_ok = False  # Not a valid bcrypt hash — try SHA-256 fallback
            
            if not pin_ok:
                # Migration: check against legacy SHA-256 hash
                legacy_hash = hashlib.sha256(data.pin.encode()).hexdigest()
                if stored_pin == legacy_hash:
                    pin_ok = True
                    # Re-hash with bcrypt and update DB
                    new_hash = bcrypt.hashpw(data.pin.encode(), bcrypt.gensalt()).decode()
                    async with aiosqlite.connect(db.DB_PATH) as conn:
                        await conn.execute(
                            "UPDATE users SET pin_hash = ? WHERE id = ?",
                            (new_hash, existing['id'])
                        )
                        await conn.commit()
                    logger.info(f"Migrated PIN hash to bcrypt for user {existing['id']}")
            
            if not pin_ok:
                raise HTTPException(
                    status_code=401,
                    detail="That PIN doesn't match. Please try again."
                )
        elif stored_pin and not data.pin:
            # Account has PIN but user didn't provide one
            raise HTTPException(
                status_code=401,
                detail="Please enter your 4-digit PIN to sign in."
            )
        elif not stored_pin and data.pin:
            # Legacy account without PIN — set the PIN now
            new_hash = bcrypt.hashpw(data.pin.encode(), bcrypt.gensalt()).decode()
            async with aiosqlite.connect(db.DB_PATH) as conn:
                await conn.execute(
                    "UPDATE users SET pin_hash = ? WHERE id = ?",
                    (new_hash, existing['id'])
                )
                await conn.commit()
            logger.info(f"PIN set for legacy user {existing['id']}")
        elif not stored_pin and not data.pin:
            # Legacy account, no PIN provided — require them to set one
            raise HTTPException(
                status_code=401,
                detail="This account needs a PIN. Please enter a 4-digit PIN to secure your account."
            )
        
        # Rotate token on re-login
        new_token = secrets.token_urlsafe(32)
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE users SET session_token = ?, token_created_at = ? WHERE id = ?",
                (new_token, datetime.now(UTC).isoformat(), existing['id'])
            )
            await conn.commit()
        
        return RegisterResponse(
            success=True,
            token=new_token,
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
            session_token=token,
            pin_hash=pin_hash
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Something didn't work. Let's try again.")
    
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

# ----- R2: Streaming Transcription -----
@app.websocket("/ws/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming transcription."""
    await websocket.accept()
    try:
        await handle_streaming_transcription(websocket)
    except WebSocketDisconnect:
        logger.info("Streaming transcription client disconnected")
    except Exception as e:
        logger.error(f"Streaming transcription error: {e}")

@app.get("/api/transcription/status")
async def api_transcription_status():
    """R2.2: Hardware detection — is transcription engine available?"""
    return get_transcription_status()

@app.post("/api/upload")
@limiter.limit("30/minute")  # SEC-9: rate limit uploads
async def upload_chunk(
    request: Request,
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

    # SEC-5b: Reject oversized uploads
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum upload size is 50MB.")

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
        started_at=datetime.now(UTC).isoformat()
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
                completed_at=datetime.now(UTC).isoformat()
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
        await db.save_cache_result(user_id, "entities", _entities_cache[user_id])
        
        # Stage 3: Build timeline
        await db.upsert_processing_status(user_id, "processing", "building_timeline", 45)
        
        timeline = await build_timeline(merged_extraction.events, merged_extraction.dates)
        _timeline_cache[user_id] = timeline
        await db.save_cache_result(user_id, "timeline", _timeline_cache[user_id])
        
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
        await db.save_cache_result(user_id, "biography", _biography_cache[user_id])
        
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
        await db.save_cache_result(user_id, "journal", _journal_cache[user_id])
        
        # Complete
        await db.upsert_processing_status(
            user_id, "complete", "complete", 100,
            completed_at=datetime.now(UTC).isoformat()
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
        cached = await db.get_cache_result(user_id, "entities")
        if cached:
            _entities_cache[user_id] = cached
        else:
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
        cached = await db.get_cache_result(user_id, "timeline")
        if cached:
            _timeline_cache[user_id] = cached
        else:
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
        cached = await db.get_cache_result(user_id, "biography")
        if cached:
            _biography_cache[user_id] = cached
        else:
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
        cached = await db.get_cache_result(user_id, "biography")
        if cached:
            _biography_cache[user_id] = cached
        else:
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

# ----- R3: Biography Exports & Enhancements -----
@app.get("/api/biography/export/pdf")
async def export_biography_pdf(
    format: str = "standard",
    authorization: str = Header(None)
):
    """R3.2/R3.8: Export biography as PDF (standard or print-ready 6x9)."""
    from .pdf_export import generate_biography_pdf
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _biography_cache:
        cached = await db.get_cache_result(user_id, "biography")
        if cached:
            _biography_cache[user_id] = cached
        else:
            raise HTTPException(status_code=404, detail="No biography to export. Generate one first.")
    
    bio = _biography_cache[user_id]
    chapters = bio.get("chapters", [])
    user_name = user.get('first_name', 'Unknown')
    birth_year = user.get('birth_year')
    
    pdf_bytes = generate_biography_pdf(
        chapters=chapters,
        user_name=user_name,
        birth_year=birth_year,
        format_type=format
    )
    
    from fastapi.responses import Response
    content_type = 'application/pdf' if pdf_bytes[:4] == b'%PDF' else 'text/html'
    filename = f"{user_name.replace(' ', '_')}_biography.pdf"
    return Response(
        content=pdf_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/biography/export/epub")
async def export_biography_epub(authorization: str = Header(None)):
    """R3.3: Export biography as EPUB e-book."""
    from .epub_export import generate_biography_epub
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _biography_cache:
        cached = await db.get_cache_result(user_id, "biography")
        if cached:
            _biography_cache[user_id] = cached
        else:
            raise HTTPException(status_code=404, detail="No biography to export.")
    
    bio = _biography_cache[user_id]
    chapters = bio.get("chapters", [])
    user_name = user.get('first_name', 'Unknown')
    birth_year = user.get('birth_year')
    
    epub_bytes = generate_biography_epub(chapters, user_name, birth_year)
    
    from fastapi.responses import Response
    filename = f"{user_name.replace(' ', '_')}_biography.epub"
    return Response(
        content=epub_bytes,
        media_type='application/epub+zip',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/recordings/{session_uuid}/chunk/{chunk_index}")
async def serve_chunk_audio(
    session_uuid: str,
    chunk_index: int,
    authorization: str = Header(None)
):
    """R3.1: Serve a specific audio chunk for citation playback."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    chunk_dir = DATA_DIR / "recordings" / str(user_id) / session_uuid
    chunk_file = chunk_dir / f"chunk_{chunk_index}.webm"
    
    if not chunk_file.exists():
        raise HTTPException(status_code=404, detail="Audio chunk not found")
    
    return FileResponse(chunk_file, media_type="audio/webm")

@app.get("/api/biography/follow-up-questions")
async def get_follow_up_questions(authorization: str = Header(None)):
    """R3.4: Generate questions to enrich the biography based on timeline gaps."""
    user = await get_current_user(authorization)
    user_id = user['id']
    
    # Get biography and check for gaps
    if user_id not in _biography_cache:
        cached = await db.get_cache_result(user_id, "biography")
        if cached:
            _biography_cache[user_id] = cached
    
    bio = _biography_cache.get(user_id, {})
    chapters = bio.get("chapters", [])
    
    # Generate questions based on gaps
    questions = []
    if not chapters:
        questions = [
            {"question": "Where and when were you born?", "category": "early_life"},
            {"question": "What is your earliest childhood memory?", "category": "childhood"},
            {"question": "Who were the most important people in your early life?", "category": "family"},
        ]
    else:
        # Analyze what's covered and suggest gaps
        default_questions = [
            {"question": "What was the happiest day of your life?", "category": "milestone"},
            {"question": "What career or job did you enjoy the most?", "category": "career"},
            {"question": "What advice would you give to your younger self?", "category": "wisdom"},
            {"question": "What family traditions mean the most to you?", "category": "family"},
            {"question": "What was the biggest challenge you overcame?", "category": "adversity"},
        ]
        # Return questions not already covered
        questions = default_questions[:3]
    
    return {
        "success": True,
        "questions": questions,
        "total": len(questions)
    }

@app.get("/api/journal/export/pdf")
async def export_journal_pdf(authorization: str = Header(None)):
    """R4.5: Export journal as PDF."""
    from .pdf_export import generate_journal_pdf
    user = await get_current_user(authorization)
    user_id = user['id']
    
    if user_id not in _journal_cache:
        cached = await db.get_cache_result(user_id, "journal")
        if cached:
            _journal_cache[user_id] = cached
        else:
            raise HTTPException(status_code=404, detail="No journal to export.")
    
    entries = _journal_cache[user_id].get("entries", [])
    user_name = user.get('first_name', 'Unknown')
    
    pdf_bytes = generate_journal_pdf(entries, user_name)
    
    from fastapi.responses import Response
    filename = f"{user_name.replace(' ', '_')}_journal.pdf"
    return Response(
        content=pdf_bytes,
        media_type='application/pdf' if pdf_bytes[:4] == b'%PDF' else 'text/html',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

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
        cached = await db.get_cache_result(user_id, "journal")
        if cached:
            _journal_cache[user_id] = cached
        else:
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
        cached = await db.get_cache_result(user_id, "journal")
        if cached:
            _journal_cache[user_id] = cached
        else:
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
    try:
        info = await asyncio.wait_for(test_connection(), timeout=3.0)
    except asyncio.TimeoutError:
        info = {"available": False, "transport": "none", "model": "none", "ollama_url": ""}
    
    return {
        "success": True,
        "available": info["available"],
        "transport": info["transport"],
        "model": info["model"],
        "ollama_url": info["ollama_url"],
        "message": f"LLM connected via {info['transport']} ({info['model']})" if info["available"]
            else "Using mock responses (no Ollama reachable)"
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


# ----- Soul Endpoints -----

class SoulChatRequest(BaseModel):
    message: str

@app.post("/api/soul/activate")
async def api_soul_activate(authorization: str = Header(None)):
    """Activate the Soul — builds RAG index over user transcripts."""
    user = await get_current_user(authorization)
    result = await activate_soul(user['id'])
    return {"success": result.get('status') != 'error', **result}

@app.post("/api/soul/chat")
async def api_soul_chat(data: SoulChatRequest, authorization: str = Header(None)):
    """Chat with the Soul."""
    user = await get_current_user(authorization)
    result = await chat_with_soul(user['id'], data.message)
    return {"success": result.get('status') == 'ok', **result}

# ----- Voice Clone Generation Endpoint -----

@app.post("/api/voice-clone/generate")
async def api_voice_clone_generate(authorization: str = Header(None)):
    """Generate a voice clone from the user's audio recordings."""
    user = await get_current_user(authorization)
    sessions = await db.get_user_sessions(user['id'])
    # Gather audio file paths from all sessions
    audio_files = []
    for session in sessions:
        session_dir = AUDIO_DIR / session['session_uuid']
        if session_dir.exists():
            for f in sorted(session_dir.iterdir()):
                if f.suffix in {'.webm', '.wav', '.mp3', '.ogg'}:
                    audio_files.append(str(f))
    result = await generate_voice_clone(user['id'], audio_files)
    return {"success": result.get('status') == 'ready', **result}

# ----- Avatar Generation Endpoint -----

@app.post("/api/avatar/generate")
async def api_avatar_generate(authorization: str = Header(None)):
    """Generate an avatar from the user's photos."""
    user = await get_current_user(authorization)
    photos = await list_user_photos(user['id'])
    photo_paths = []
    for photo in photos:
        p = PHOTOS_DIR / str(user['id']) / photo['filename']
        if p.exists():
            photo_paths.append(str(p))
    sessions = await db.get_user_sessions(user['id'])
    video_hours = sum(s['total_duration_seconds'] for s in sessions) / 3600
    result = await generate_avatar(user['id'], photo_paths, video_hours)
    return {"success": result.get('status') == 'ready', **result}

# ----- Payment Endpoints -----

class CheckoutRequest(BaseModel):
    product_id: str

@app.post("/api/checkout")
async def api_checkout(data: CheckoutRequest, authorization: str = Header(None)):
    """Create a Stripe checkout session for a product."""
    user = await get_current_user(authorization)
    result = await create_checkout_session(user['id'], data.product_id, user.get('email'))
    return {"success": result.get('status') == 'created', **result}

@app.get("/api/products")
async def api_products():
    """List all available products and prices."""
    return {"success": True, "products": list_products()}

@app.post("/api/webhook/stripe")
async def api_stripe_webhook(request: Request):
    """Handle Stripe webhook events (payment confirmations)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    result = await stripe_handle_webhook(payload, sig_header)
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result.get('message'))
    return result

# ----- Delete Endpoints -----

@app.delete("/api/session/{session_id}")
async def delete_session(session_id: int, authorization: str = Header(None)):
    """Delete a recording session and all its chunks/transcripts."""
    user = await get_current_user(authorization)
    deleted = await db.delete_recording_session(session_id, user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found or not yours")
    return {"success": True, "message": "Session deleted."}


@app.delete("/api/transcript/{transcript_id}")
async def delete_transcript(transcript_id: int, authorization: str = Header(None)):
    """Delete a single transcript."""
    user = await get_current_user(authorization)
    deleted = await db.delete_transcript(transcript_id, user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail="Transcript not found or not yours")
    return {"success": True, "message": "Transcript deleted."}


# ----- Error Handlers -----

@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors - serve index for SPA routing."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"}
        )
    # Serve known pages
    page_map = {
        "/soul": "soul.html",
        "/gift": "gift.html",
        "/family": "family.html",
        "/pricing": "pricing.html",
        "/tv": "tv.html",
        "/consent": "consent.html",
    }
    for route, page in page_map.items():
        if request.url.path == route:
            page_file = STATIC_DIR / page
            if page_file.exists():
                return FileResponse(page_file)
    return FileResponse(STATIC_DIR / "index.html")


# ----- Consent Endpoints -----

class ConsentRequest(BaseModel):
    tier: int
    accepted: bool

@app.post("/api/consent")
async def save_consent_endpoint(data: ConsentRequest, authorization: str = Header(None)):
    """Record consent acceptance or rejection for a specific tier."""
    user = await get_current_user(authorization)
    await db.save_consent(user['id'], data.tier, data.accepted)
    await db.log_audit(user['id'], "consent_update", f"tier_{data.tier}",
                       f"{'accepted' if data.accepted else 'rejected'}")
    return {
        "success": True,
        "tier": data.tier,
        "accepted": data.accepted,
        "message": f"Consent for tier {data.tier} {'accepted' if data.accepted else 'rejected'}."
    }

@app.get("/api/consents")
async def get_consents_endpoint(authorization: str = Header(None)):
    """Get user's consent status for all tiers."""
    user = await get_current_user(authorization)
    consents = await db.get_user_consents(user['id'])
    return {"success": True, "consents": consents}


# ----- Audit Log Endpoints -----

@app.get("/api/audit-log")
async def get_audit_log_endpoint(authorization: str = Header(None)):
    """Get audit log entries for the current user."""
    user = await get_current_user(authorization)
    entries = await db.get_audit_log(user['id'])
    return {"success": True, "entries": entries}


# ----- Account Deletion -----

@app.delete("/api/account")
async def delete_account_endpoint(authorization: str = Header(None)):
    """Delete user account and ALL associated data. This is irreversible."""
    user = await get_current_user(authorization)
    user_id = user['id']

    # Log the deletion attempt (will be deleted along with account)
    await db.log_audit(user_id, "account_deletion", "account", "User requested account deletion")

    # Delete audio files from disk
    import shutil
    user_audio_dirs = list(AUDIO_DIR.glob("*"))
    sessions = await db.get_user_sessions(user_id)
    for session in sessions:
        session_dir = AUDIO_DIR / session['session_uuid']
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

    # Delete photos from disk
    photos_dir = PHOTOS_DIR / str(user_id)
    if photos_dir.exists():
        shutil.rmtree(photos_dir, ignore_errors=True)

    # Delete from database
    deleted = await db.delete_user_account(user_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Account deletion failed")

    return {"success": True, "message": "Your account and all data have been permanently deleted."}


# ----- Biography Share Endpoints -----

class ShareRequest(BaseModel):
    chapter_number: int
    recipient_name: Optional[str] = None

@app.post("/api/biography/share")
async def create_share_endpoint(data: ShareRequest, authorization: str = Header(None)):
    """Create a shareable link for a biography chapter."""
    user = await get_current_user(authorization)
    share_token = secrets.token_urlsafe(16)
    result = await db.create_share_link(
        user['id'], data.chapter_number, share_token, data.recipient_name
    )
    await db.log_audit(user['id'], "share_created", f"chapter_{data.chapter_number}")
    return {
        "success": True,
        "share_url": f"/share/{share_token}",
        "share_token": share_token,
        **result
    }

@app.get("/api/share/{token}")
async def view_share_endpoint(token: str):
    """View a shared biography chapter (public, no auth required)."""
    share = await db.get_share_link(token)
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    # Get the biography chapter
    user_id = share['user_id']
    chapter_num = share['chapter_number']

    cached = await db.get_cache_result(user_id, "biography")
    if not cached:
        return {"success": False, "message": "Biography not yet generated."}

    chapters = cached.get("chapters", [])
    chapter = None
    for c in chapters:
        if c.get("number") == chapter_num:
            chapter = c
            break

    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    return {
        "success": True,
        "author_name": share.get('first_name', 'Someone'),
        "chapter": chapter,
        "shared_by": share.get('recipient_name'),
    }


# ----- Download Recordings -----

@app.get("/api/recordings/download/{session_uuid}")
async def download_recording(session_uuid: str, authorization: str = Header(None)):
    """Download all audio chunks for a session as individual files list."""
    user = await get_current_user(authorization)

    session = await db.get_session_by_uuid(session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session['user_id'] != user['id']:
        raise HTTPException(status_code=403, detail="Access denied")

    session_dir = AUDIO_DIR / session_uuid
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Audio files not found")

    files = sorted(session_dir.iterdir())
    audio_files = [f.name for f in files if f.suffix in {'.webm', '.wav', '.mp3', '.ogg'}]

    await db.log_audit(user['id'], "download_recording", session_uuid)
    return {
        "success": True,
        "session_uuid": session_uuid,
        "files": audio_files,
        "download_urls": [f"/api/recordings/file/{session_uuid}/{f}" for f in audio_files]
    }

@app.get("/api/recordings/file/{session_uuid}/{filename}")
async def serve_recording_file(session_uuid: str, filename: str, authorization: str = Header(None)):
    """Serve an individual audio file for download."""
    user = await get_current_user(authorization)

    session = await db.get_session_by_uuid(session_uuid)
    if not session or session['user_id'] != user['id']:
        raise HTTPException(status_code=403, detail="Access denied")

    file_path = AUDIO_DIR / session_uuid / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path, filename=filename)


# ----- Family Sharing Endpoints -----

class FamilyInviteRequest(BaseModel):
    email: str
    name: Optional[str] = None
    role: str = "viewer"

class StewardRequest(BaseModel):
    steward_email: str

@app.post("/api/family/invite")
async def invite_family_member(data: FamilyInviteRequest, authorization: str = Header(None)):
    """Invite a family member to view your legacy."""
    user = await get_current_user(authorization)
    invite_token = secrets.token_urlsafe(16)
    result = await db.add_family_member(
        user['id'], data.email, data.name, data.role, invite_token
    )
    await db.log_audit(user['id'], "family_invite", data.email)
    return {"success": True, "invite_token": invite_token, **result}

@app.get("/api/family/members")
async def get_family_members_endpoint(authorization: str = Header(None)):
    """List all family members."""
    user = await get_current_user(authorization)
    members = await db.get_family_members(user['id'])
    return {"success": True, "members": members}

@app.delete("/api/family/member/{member_id}")
async def remove_family_member_endpoint(member_id: int, authorization: str = Header(None)):
    """Remove a family member."""
    user = await get_current_user(authorization)
    removed = await db.remove_family_member(user['id'], member_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Family member not found")
    return {"success": True, "message": "Family member removed."}

@app.post("/api/family/steward")
async def set_steward_endpoint(data: StewardRequest, authorization: str = Header(None)):
    """Designate a steward for your account."""
    user = await get_current_user(authorization)
    await db.set_steward(user['id'], data.steward_email)
    await db.log_audit(user['id'], "steward_set", data.steward_email)
    return {
        "success": True,
        "message": f"{data.steward_email} has been designated as your steward.",
        "steward_email": data.steward_email
    }


# ----- Notification Endpoints -----

@app.get("/api/notifications")
async def get_notifications_endpoint(
    unread_only: bool = False,
    authorization: str = Header(None)
):
    """Get notifications for the current user."""
    user = await get_current_user(authorization)
    notifications = await db.get_notifications(user['id'], unread_only)
    return {"success": True, "notifications": notifications}

@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read_endpoint(notification_id: int, authorization: str = Header(None)):
    """Mark a notification as read."""
    user = await get_current_user(authorization)
    marked = await db.mark_notification_read(notification_id, user['id'])
    if not marked:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


# ----- Biography PDF (Client-side print) -----

@app.get("/api/biography/pdf")
async def get_biography_pdf(authorization: str = Header(None)):
    """Return biography data formatted for PDF generation (client-side print)."""
    user = await get_current_user(authorization)
    user_id = user['id']

    cached = await db.get_cache_result(user_id, "biography")
    if not cached:
        return {"success": False, "message": "No biography generated yet."}

    await db.log_audit(user_id, "biography_pdf_export", "biography")
    return {
        "success": True,
        "biography": cached,
        "print_ready": True,
        "message": "Use Ctrl+P or the print button to save as PDF."
    }


# ----- Biography Review / Approval -----

class ReviewRequest(BaseModel):
    approved: bool
    notes: Optional[str] = None

@app.post("/api/biography/review")
async def review_biography(data: ReviewRequest, authorization: str = Header(None)):
    """Mark biography as approved or request changes."""
    user = await get_current_user(authorization)
    status = "approved" if data.approved else "needs_changes"
    await db.save_cache_result(user['id'], "biography_review", {
        "status": status,
        "notes": data.notes,
        "reviewed_at": datetime.now(UTC).isoformat()
    })
    await db.log_audit(user['id'], "biography_review", "biography", status)

    if data.approved:
        await db.create_notification(
            user['id'], "biography", "Biography Approved! 📖",
            "Your biography has been approved and is ready to share."
        )

    return {
        "success": True,
        "status": status,
        "message": "Biography approved! You can now share or export it." if data.approved
                   else "Changes requested. We'll regenerate your biography."
    }


# ----- Gift Endpoints -----

class GiftRedeemRequest(BaseModel):
    gift_code: str

@app.post("/api/gift/redeem")
async def redeem_gift(data: GiftRedeemRequest, authorization: str = Header(None)):
    """Redeem a gift code."""
    user = await get_current_user(authorization)
    # Check if gift code exists in cache
    gift = await db.get_cache_result(0, f"gift_{data.gift_code}")
    if not gift:
        raise HTTPException(status_code=404, detail="Invalid or expired gift code")
    if gift.get('redeemed'):
        raise HTTPException(status_code=400, detail="Gift code already redeemed")

    # Mark as redeemed
    gift['redeemed'] = True
    gift['redeemed_by'] = user['id']
    gift['redeemed_at'] = datetime.now(UTC).isoformat()
    await db.save_cache_result(0, f"gift_{data.gift_code}", gift)

    await db.create_notification(
        user['id'], "gift", "Gift Redeemed! 🎁",
        f"You've redeemed a gift: {gift.get('product_name', 'InstaBio Gift')}"
    )

    return {
        "success": True,
        "product": gift.get('product_name'),
        "message": f"Gift redeemed! You now have access to {gift.get('product_name', 'your gift')}."
    }


# ----- Journal Calendar View -----

@app.get("/api/journal/calendar")
async def get_journal_calendar(authorization: str = Header(None)):
    """Get journal data formatted for calendar view."""
    user = await get_current_user(authorization)
    user_id = user['id']

    if user_id not in _journal_cache:
        cached = await db.get_cache_result(user_id, "journal")
        if cached:
            _journal_cache[user_id] = cached
        else:
            return {"success": False, "message": "No journal generated yet."}

    journal = _journal_cache[user_id]
    entries = journal.get("entries", [])

    # Group entries by year-month for calendar display
    calendar = {}
    for entry in entries:
        date_str = entry.get("date", "")
        # Try to extract year
        parts = date_str.split()
        year = None
        month = None
        for p in parts:
            if p.isdigit() and len(p) == 4:
                year = int(p)
            elif p.isdigit():
                month = p

        key = str(year) if year else "Unknown"
        if key not in calendar:
            calendar[key] = []
        calendar[key].append({
            "date": date_str,
            "title": entry.get("title", ""),
            "preview": (entry.get("content", "") or entry.get("text", ""))[:100],
        })

    return {
        "success": True,
        "calendar": calendar,
        "total_entries": len(entries)
    }


# ----- Page Routes for New HTML Pages -----

@app.get("/soul")
async def serve_soul_page():
    """Serve the Soul chat page."""
    return FileResponse(STATIC_DIR / "soul.html")

@app.get("/gift")
async def serve_gift_page():
    """Serve the gift purchase page."""
    return FileResponse(STATIC_DIR / "gift.html")

@app.get("/family")
async def serve_family_page():
    """Serve the family sharing page."""
    return FileResponse(STATIC_DIR / "family.html")

