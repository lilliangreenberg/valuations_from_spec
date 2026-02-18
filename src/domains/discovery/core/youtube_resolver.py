"""YouTube video-to-channel URL resolution helpers."""

from __future__ import annotations

import re

YOUTUBE_VIDEO_PATTERN = re.compile(r"youtube\.com/embed/([a-zA-Z0-9_-]+)", re.IGNORECASE)

YOUTUBE_WATCH_PATTERN = re.compile(r"youtube\.com/watch\?v=([a-zA-Z0-9_-]+)", re.IGNORECASE)


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from embed or watch URL."""
    for pattern in [YOUTUBE_VIDEO_PATTERN, YOUTUBE_WATCH_PATTERN]:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def build_oembed_url(video_id: str) -> str:
    """Build YouTube oEmbed API URL for a video ID."""
    return (
        f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    )


def is_youtube_embed_url(url: str) -> bool:
    """Check if URL is a YouTube embed URL."""
    return bool(YOUTUBE_VIDEO_PATTERN.search(url))


def is_youtube_video_url(url: str) -> bool:
    """Check if URL is a YouTube watch URL."""
    return bool(YOUTUBE_WATCH_PATTERN.search(url))
