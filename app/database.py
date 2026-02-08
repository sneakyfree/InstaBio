"""
InstaBio Database Module
SQLite database for users, sessions, and transcripts
"""

import aiosqlite
import os
from datetime import datetime
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "instabio.db"

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
        
        await db.commit()
        print("✅ Database initialized successfully")

async def create_user(first_name: str, birth_year: int, email: str, session_token: str) -> int:
    """Create a new user and return their ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO users (first_name, birth_year, email, session_token)
            VALUES (?, ?, ?, ?)
            """,
            (first_name, birth_year, email.lower(), session_token)
        )
        await db.commit()
        return cursor.lastrowid

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

async def get_pending_chunks() -> list:
    """Get audio chunks pending transcription."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT ac.*, rs.user_id 
            FROM audio_chunks ac
            JOIN recording_sessions rs ON ac.session_id = rs.id
            WHERE ac.transcription_status = 'pending'
            ORDER BY ac.uploaded_at ASC
            """
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
