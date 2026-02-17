"""
InstaBio Database Module
SQLite database for users, sessions, and transcripts
"""

import aiosqlite
import json
import os
from datetime import datetime, UTC
from pathlib import Path

# Database path — configurable via env for test isolation
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "instabio.db")))

async def get_db():
    """Get database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    """Initialize database tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                birth_year INTEGER NOT NULL,
                email TEXT UNIQUE NOT NULL,
                session_token TEXT UNIQUE,
                token_created_at TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Recording sessions table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recording_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_uuid TEXT UNIQUE NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                total_duration_seconds REAL DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Audio chunks table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audio_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                duration_seconds REAL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                transcription_status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                FOREIGN KEY (session_id) REFERENCES recording_sessions(id)
            )
        """)
        
        # Transcripts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                language TEXT,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                transcript_type TEXT DEFAULT 'whisper',
                FOREIGN KEY (chunk_id) REFERENCES audio_chunks(id),
                FOREIGN KEY (session_id) REFERENCES recording_sessions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Create indexes for faster queries
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user 
            ON recording_sessions(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_session 
            ON audio_chunks(session_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcripts_user 
            ON transcripts(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_transcripts_session 
            ON transcripts(session_id)
        """)
        
        # Safe migration — add retry_count to audio_chunks if missing
        try:
            await db.execute("ALTER TABLE audio_chunks ADD COLUMN retry_count INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE audio_chunks ADD COLUMN last_error TEXT")
        except Exception:
            pass
        
        # Safe migration — add token_created_at if missing (for existing DBs)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN token_created_at TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists
        
        # Safe migration — add pin_hash column (B2: PIN auth)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists
        
        # Interview sessions table (B3: persist interview state)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Processing status table (B4: persist processing state)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS processing_status (
                user_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'idle',
                stage TEXT DEFAULT '',
                progress INTEGER DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                error TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Cache results table (G10: persist pipeline output caches)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cache_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                cache_key TEXT NOT NULL,
                data_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, cache_key),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        await db.commit()
        print("✅ Database initialized successfully")

async def create_user(first_name: str, birth_year: int, email: str, session_token: str, pin_hash: str = '') -> int:
    """Create a new user and return their ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO users (first_name, birth_year, email, session_token, token_created_at, pin_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (first_name, birth_year, email.lower(), session_token, datetime.now(UTC).isoformat(), pin_hash)
        )
        await db.commit()
        return cursor.lastrowid

async def invalidate_token(user_id: int) -> None:
    """Invalidate a user's session token (logout)."""
    import secrets
    new_token = secrets.token_urlsafe(32)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET session_token = ?, token_created_at = '' WHERE id = ?",
            (new_token, user_id)
        )
        await db.commit()

async def get_user_by_token(token: str) -> dict | None:
    """Get user by session token."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE session_token = ?",
            (token,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_user_by_email(email: str) -> dict | None:
    """Get user by email."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.lower(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def create_recording_session(user_id: int, session_uuid: str) -> int:
    """Create a new recording session."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO recording_sessions (user_id, session_uuid)
            VALUES (?, ?)
            """,
            (user_id, session_uuid)
        )
        await db.commit()
        return cursor.lastrowid

async def save_audio_chunk(session_id: int, chunk_index: int, file_path: str, duration: float) -> int:
    """Save an audio chunk record."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO audio_chunks (session_id, chunk_index, file_path, duration_seconds)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, chunk_index, file_path, duration)
        )
        # Update session totals
        await db.execute(
            """
            UPDATE recording_sessions 
            SET chunk_count = chunk_count + 1,
                total_duration_seconds = total_duration_seconds + ?
            WHERE id = ?
            """,
            (duration, session_id)
        )
        await db.commit()
        return cursor.lastrowid

async def save_transcript(chunk_id: int, session_id: int, user_id: int, 
                         text: str, language: str = None, confidence: float = None) -> int:
    """Save a transcript."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO transcripts (chunk_id, session_id, user_id, text, language, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, session_id, user_id, text, language, confidence)
        )
        # Mark chunk as transcribed
        await db.execute(
            "UPDATE audio_chunks SET transcription_status = 'completed' WHERE id = ?",
            (chunk_id,)
        )
        await db.commit()
        return cursor.lastrowid

async def get_user_sessions(user_id: int) -> list:
    """Get all recording sessions for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM recording_sessions 
            WHERE user_id = ? 
            ORDER BY started_at DESC
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_user_transcripts(user_id: int, search_query: str = None) -> list:
    """Get all transcripts for a user, optionally filtered by search."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        if search_query:
            cursor = await db.execute(
                """
                SELECT t.*, rs.session_uuid, rs.started_at as session_started_at
                FROM transcripts t
                JOIN recording_sessions rs ON t.session_id = rs.id
                WHERE t.user_id = ? AND t.text LIKE ?
                ORDER BY t.created_at DESC
                """,
                (user_id, f"%{search_query}%")
            )
        else:
            cursor = await db.execute(
                """
                SELECT t.*, rs.session_uuid, rs.started_at as session_started_at
                FROM transcripts t
                JOIN recording_sessions rs ON t.session_id = rs.id
                WHERE t.user_id = ?
                ORDER BY t.created_at DESC
                """,
                (user_id,)
            )
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_pending_chunks(max_retries: int = 3) -> list:
    """Get audio chunks pending transcription, skipping those with too many retries."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT ac.*, rs.user_id 
            FROM audio_chunks ac
            JOIN recording_sessions rs ON ac.session_id = rs.id
            WHERE ac.transcription_status = 'pending'
              AND COALESCE(ac.retry_count, 0) < ?
            ORDER BY ac.uploaded_at ASC
            """,
            (max_retries,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_session_by_uuid(session_uuid: str) -> dict | None:
    """Get recording session by UUID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM recording_sessions WHERE session_uuid = ?",
            (session_uuid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def mark_chunk_failed(chunk_id: int, error_msg: str) -> None:
    """Increment retry count; mark as permanently 'failed' after 3 retries."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE audio_chunks 
            SET retry_count = COALESCE(retry_count, 0) + 1,
                last_error = ?,
                transcription_status = CASE 
                    WHEN COALESCE(retry_count, 0) + 1 >= 3 THEN 'failed'
                    ELSE 'pending'
                END
            WHERE id = ?
            """,
            (error_msg, chunk_id)
        )
        await db.commit()


# ----- Interview Session Persistence (B3) -----

async def save_interview_session(session_id: str, user_id: int, data: str) -> None:
    """Save or update an interview session (JSON blob)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO interview_sessions (session_id, user_id, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
            """,
            (session_id, user_id, data, datetime.now(UTC).isoformat())
        )
        await db.commit()

async def get_interview_session(session_id: str) -> dict | None:
    """Get an interview session by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM interview_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def delete_interview_session(session_id: str) -> None:
    """Delete an interview session."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM interview_sessions WHERE session_id = ?",
            (session_id,)
        )
        await db.commit()


# ----- Recording / Transcript Deletion -----

async def delete_recording_session(session_id: int, user_id: int) -> bool:
    """Delete a recording session and its chunks/transcripts. Returns True if deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Verify ownership
        cursor = await db.execute(
            "SELECT id FROM recording_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id)
        )
        if not await cursor.fetchone():
            return False
        # Delete transcripts linked to this session
        await db.execute("DELETE FROM transcripts WHERE session_id = ?", (session_id,))
        # Delete audio chunks
        await db.execute("DELETE FROM audio_chunks WHERE session_id = ?", (session_id,))
        # Delete the session itself
        await db.execute("DELETE FROM recording_sessions WHERE id = ?", (session_id,))
        await db.commit()
        return True


async def delete_transcript(transcript_id: int, user_id: int) -> bool:
    """Delete a single transcript. Returns True if deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM transcripts WHERE id = ? AND user_id = ?",
            (transcript_id, user_id)
        )
        if not await cursor.fetchone():
            return False
        await db.execute("DELETE FROM transcripts WHERE id = ?", (transcript_id,))
        await db.commit()
        return True


# ----- Processing Status Persistence (B4) -----

async def upsert_processing_status(user_id: int, status: str, stage: str = '', progress: int = 0,
                                    started_at: str = None, completed_at: str = None, error: str = None) -> None:
    """Insert or update processing status for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO processing_status (user_id, status, stage, progress, started_at, completed_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                status = excluded.status,
                stage = excluded.stage,
                progress = excluded.progress,
                started_at = COALESCE(excluded.started_at, processing_status.started_at),
                completed_at = excluded.completed_at,
                error = excluded.error
            """,
            (user_id, status, stage, progress, started_at, completed_at, error)
        )
        await db.commit()

async def get_processing_status(user_id: int) -> dict | None:
    """Get processing status for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM processing_status WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def save_cache_result(user_id: int, cache_key: str, data: dict) -> None:
    """Save or update a cached pipeline result (G10)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            INSERT INTO cache_results (user_id, cache_key, data_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, cache_key) DO UPDATE SET
                data_json = excluded.data_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, cache_key, json.dumps(data))
        )
        await conn.commit()

async def get_cache_result(user_id: int, cache_key: str) -> dict | None:
    """Retrieve a cached pipeline result (G10)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT data_json FROM cache_results WHERE user_id = ? AND cache_key = ?",
            (user_id, cache_key)
        )
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
