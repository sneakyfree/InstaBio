#!/bin/bash
# InstaBio Phase 1 - Quick Start Script
# Run this to install dependencies and start the server

set -e

echo "🌱 InstaBio - Starting up..."
echo ""

# Check Python version
python3 --version || { echo "❌ Python 3 not found. Please install Python 3.10+"; exit 1; }

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
mkdir -p data/audio
mkdir -p data/transcripts

# Initialize database
echo "🗄️ Initializing database..."
python3 -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting InstaBio server on http://localhost:8000"
echo "   Press Ctrl+C to stop"
echo ""

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
