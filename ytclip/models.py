from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum


class OutputFormat(str, Enum):
    MP4 = "mp4"
    MKV = "mkv"
    MP3 = "mp3"
    AAC = "aac"


class JobStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClipJob:
    __slots__ = (
        "id", "status", "url", "video_title", "start_time", "end_time",
        "output_format", "include_subtitles", "quality", "output_path",
        "output_filename", "error_message", "progress", "created_at",
        "updated_at", "completed_at",
    )

    def __init__(
        self,
        id: str,
        url: str,
        start_time: float,
        end_time: float,
        output_format: OutputFormat = OutputFormat.MP4,
        include_subtitles: bool = False,
        quality: str = "best",
        status: JobStatus = JobStatus.QUEUED,
        video_title: str | None = None,
        output_path: str | None = None,
        output_filename: str | None = None,
        error_message: str | None = None,
        progress: float = 0.0,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        completed_at: datetime | None = None,
    ):
        self.id = id
        self.url = url
        self.start_time = start_time
        self.end_time = end_time
        self.output_format = OutputFormat(output_format)
        self.include_subtitles = include_subtitles
        self.quality = quality
        self.status = JobStatus(status)
        self.video_title = video_title
        self.output_path = output_path
        self.output_filename = output_filename
        self.error_message = error_message
        self.progress = progress
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.completed_at = completed_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "url": self.url,
            "video_title": self.video_title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "output_format": self.output_format.value,
            "include_subtitles": self.include_subtitles,
            "quality": self.quality,
            "output_path": self.output_path,
            "output_filename": self.output_filename,
            "error_message": self.error_message,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS, MM:SS, or raw seconds to float seconds."""
    time_str = time_str.strip()
    parts = time_str.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise ValueError(f"Invalid time format: {time_str!r}. Use HH:MM:SS, MM:SS, or seconds.")


def format_time(seconds: float) -> str:
    """Format float seconds to MM:SS or HH:MM:SS."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def generate_filename(template: str, title: str, start: float, end: float, job_id: str, ext: str) -> str:
    """Generate output filename from template."""
    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        if h > 0:
            return f"{h:02d}{m:02d}{s:02d}"
        return f"{m:02d}{s:02d}"

    safe_title = re.sub(r"[^\w\s-]", "", title or "clip").strip()
    safe_title = re.sub(r"[\s]+", "_", safe_title)[:60]
    safe_title = safe_title or "clip"

    name = template.format(
        title=safe_title,
        start=fmt(start),
        end=fmt(end),
        id=job_id[:8],
    )
    return f"{name}.{ext}"
