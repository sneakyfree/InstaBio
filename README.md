# 🌿 InstaBio — Your Story. Forever.

AI-powered life memoir platform. Record your life story by voice, and InstaBio transforms it into a biography, journal, voice clone, avatar, and interactive AI legacy.

## 🎯 The Vision

A grandmother sits in her rocking chair. She opens her phone. Taps the green button. Talks about her life for hours. Everything is recorded. Nothing is lost.

Years later, her family gathers. They hear her voice. They see her face. They ask her questions. And she answers.

## 🚀 Quick Start

```bash
./start.sh
# Visit http://localhost:8000
```

Or with Docker:
```bash
docker-compose up -d
```

## 📱 Features

### Phase 1 — Recording (✅ Complete)
- Big green RECORD button — grandma-proof
- Live transcription on screen while speaking
- 30-second stream chunking (zero data loss)
- Green pulse border while recording
- Red flash on pause/interruption
- Background upload over Wi-Fi
- Life Vault archive with search

### Phase 2 — Story Engine (✅ Complete)
- Entity extraction (people, places, dates, events)
- Confidence scoring on extracted facts
- Multi-chapter biography generation
- Retroactive life journal reconstruction
- Audio citation linking

### Phase 3-5 — Products (✅ Status Tracking)
- Voice clone quality tiers (based on recording hours)
- Avatar readiness tracking
- Soul (interactive AI) progress
- 5-product progress dashboard

## 🏗️ Tech Stack

- **Frontend:** Vanilla JS PWA (no build step)
- **Backend:** Python FastAPI
- **Transcription:** Faster Whisper (CPU)
- **Database:** SQLite
- **LLM:** Ollama (Qwen 2.5:32b on GPU)

## 📖 DNA Master Plan

See [DNA-MASTER-PLAN.md](DNA-MASTER-PLAN.md) for the complete blueprint.

## 📄 License

Copyright © 2026 InstaBio, Inc. All rights reserved.
