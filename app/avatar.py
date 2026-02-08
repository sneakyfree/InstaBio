"""
InstaBio Avatar Status Module
Tracks avatar readiness based on photos and video recordings.

Avatar Tiers:
- No photos: "Upload a photo to get started" (0%)
- 1 photo: Tier 1 — Static portrait with lip sync (30%)
- 2-5 photos: Tier 1+ — Better angle coverage (50%)
- Video recordings (any): Tier 2 — Dynamic avatar (70%)
- 10+ hours video: Tier 3 — High-fidelity digital twin (95%)
"""

from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

# Photo directory
PHOTOS_DIR = Path(__file__).parent.parent / "data" / "photos"


@dataclass
class AvatarStatus:
    """Status object for avatar readiness."""
    tier: float
    tier_name: str
    quality_pct: int
    photos_uploaded: int
    video_hours: float
    tips: List[str]
    next_step: str
    is_ready: bool


def calculate_avatar_status(photos_count: int, video_hours: float = 0.0) -> AvatarStatus:
    """
    Calculate avatar readiness status.
    
    Args:
        photos_count: Number of photos uploaded
        video_hours: Hours of video recordings (face on camera)
        
    Returns:
        AvatarStatus with tier info, quality percentage, and tips
    """
    tips = []
    
    # Determine tier based on photos and video
    if photos_count == 0:
        tier = 0
        tier_name = "Not Started"
        quality_pct = 0
        next_step = "Upload a photo to get started!"
        tips = [
            "Upload a clear, front-facing photo",
            "Good lighting makes a big difference",
            "Neutral expression works best for the base avatar"
        ]
        is_ready = False
        
    elif photos_count == 1 and video_hours < 0.1:
        tier = 1
        tier_name = "Tier 1 — Static Portrait"
        quality_pct = 30
        next_step = "Upload more photos from different angles for better coverage"
        tips = [
            "Add photos from different angles (side profile, 3/4 view)",
            "Include photos with different expressions",
            "Recording video will dramatically improve your avatar"
        ]
        is_ready = True
        
    elif photos_count >= 2 and video_hours < 0.1:
        # More photos = better coverage
        coverage_bonus = min(photos_count - 1, 5) * 4  # Up to 20% bonus
        tier = 1.5
        tier_name = "Tier 1+ — Better Coverage"
        quality_pct = 50 + coverage_bonus
        next_step = "Record a video session to unlock your dynamic avatar!"
        tips = [
            "A video recording will capture your expressions and mannerisms",
            "Even a few minutes of video helps a lot",
            "Your avatar will be able to move naturally"
        ]
        is_ready = True
        
    elif video_hours < 10:
        tier = 2
        tier_name = "Tier 2 — Dynamic Avatar"
        # Scale from 70% at 0 hours to 94% at 10 hours
        video_bonus = int((video_hours / 10) * 25)
        quality_pct = 70 + video_bonus
        next_step = f"Record {10 - video_hours:.1f} more hours of video for ultra-high fidelity!"
        tips = [
            "More video = smoother, more natural movements",
            "Try to capture a range of expressions",
            "Good lighting during recording helps quality"
        ]
        is_ready = True
        
    else:  # 10+ hours of video
        tier = 3
        tier_name = "Tier 3 — Digital Twin"
        quality_pct = 95 + min(int(video_hours - 10) // 10, 4)  # Up to 99%
        next_step = "Your avatar is incredible! Keep recording to maintain freshness."
        tips = [
            "Your digital twin captures your full range of expressions",
            "Family will be amazed at how lifelike it is",
            "Consider recording in different outfits for variety"
        ]
        is_ready = True
    
    return AvatarStatus(
        tier=tier,
        tier_name=tier_name,
        quality_pct=min(quality_pct, 99),  # Cap at 99%
        photos_uploaded=photos_count,
        video_hours=round(video_hours, 2),
        tips=tips,
        next_step=next_step,
        is_ready=is_ready
    )


def get_avatar_status_dict(photos_count: int, video_hours: float = 0.0) -> dict:
    """Get avatar status as a dictionary for API responses."""
    status = calculate_avatar_status(photos_count, video_hours)
    return {
        "tier": status.tier,
        "tier_name": status.tier_name,
        "quality_pct": status.quality_pct,
        "photos_uploaded": status.photos_uploaded,
        "video_hours": status.video_hours,
        "tips": status.tips,
        "next_step": status.next_step,
        "is_ready": status.is_ready,
    }


async def count_user_photos(user_id: int) -> int:
    """Count photos uploaded by a user."""
    user_photos_dir = PHOTOS_DIR / str(user_id)
    if not user_photos_dir.exists():
        return 0
    
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    count = 0
    for file in user_photos_dir.iterdir():
        if file.suffix.lower() in valid_extensions:
            count += 1
    return count


async def list_user_photos(user_id: int) -> list:
    """List all photos for a user."""
    user_photos_dir = PHOTOS_DIR / str(user_id)
    if not user_photos_dir.exists():
        return []
    
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    photos = []
    for file in user_photos_dir.iterdir():
        if file.suffix.lower() in valid_extensions:
            photos.append({
                "filename": file.name,
                "path": f"/api/photos/{user_id}/{file.name}",
                "size_bytes": file.stat().st_size,
                "uploaded_at": file.stat().st_mtime,
            })
    
    return sorted(photos, key=lambda x: x['uploaded_at'], reverse=True)


async def save_user_photo(user_id: int, filename: str, content: bytes) -> dict:
    """Save a photo for a user."""
    import uuid
    
    user_photos_dir = PHOTOS_DIR / str(user_id)
    user_photos_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename to prevent collisions
    ext = Path(filename).suffix.lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp', '.heic'}:
        ext = '.jpg'  # Default
    
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    file_path = user_photos_dir / unique_name
    
    with open(file_path, 'wb') as f:
        f.write(content)
    
    return {
        "success": True,
        "filename": unique_name,
        "path": f"/api/photos/{user_id}/{unique_name}",
        "size_bytes": len(content),
    }


# ----- Placeholder for avatar generation -----

async def generate_avatar(user_id: int, photos: list, video_hours: float) -> dict:
    """
    Placeholder for avatar generation.
    
    In production, this would:
    1. Process photos with SadTalker/LivePortrait (Tier 1)
    2. Process video with HeyGen/Hedra (Tier 2)
    3. Create high-fidelity model (Tier 3)
    
    For now, returns a mock response.
    """
    return {
        "status": "pending",
        "message": "Avatar generation coming soon! We're integrating advanced video synthesis.",
        "estimated_tier": "Depends on your photos and videos",
        "api_ready": False,
    }
