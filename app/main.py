"""
InstaBio - Main FastAPI Application
Phase 1: The Seed - Recording MVP

Your story. Forever.
"""

import os
import uuid
import secrets
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from . import database as db
from .transcription import transcribe_audio, transcribe_pending_chunks, is_whisper_available

# ----- Configuration -----
BASE_DIR = Path(__file__).parent.parent
AUDIO_DIR = BASE_DIR / "data" / "audio"
STATIC_DIR = BASE_DIR / "static"

# Ensure directories exist
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
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

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "whisper_available": is_whisper_available(),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    Register a new user.
    For MVP: simple name + email, no password required.
    Returns a session token for subsequent requests.
    """
    # Check if email already exists
    existing = await db.get_user_by_email(request.email)
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
            first_name=request.first_name,
            birth_year=request.birth_year,
            email=request.email,
            session_token=token
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")
    
    return RegisterResponse(
        success=True,
        token=token,
        user_id=user_id,
        first_name=request.first_name,
        message=f"Welcome, {request.first_name}! Your story begins now."
    )

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

# ----- Service Worker & Manifest -----

@app.get("/manifest.json")
async def manifest():
    """Serve PWA manifest."""
    return FileResponse(STATIC_DIR / "manifest.json")

@app.get("/sw.js")
async def service_worker():
    """Serve service worker."""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

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
