from __future__ import annotations

import json
import uuid
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path

from .models import ClipJob, JobStatus, OutputFormat

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    url TEXT NOT NULL,
    video_title TEXT,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    output_format TEXT NOT NULL DEFAULT 'mp4',
    include_subtitles INTEGER NOT NULL DEFAULT 0,
    quality TEXT NOT NULL DEFAULT 'best',
    output_path TEXT,
    output_filename TEXT,
    error_message TEXT,
    progress REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
"""

_CREATE_WATERMARK_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS watermark_history (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    value TEXT NOT NULL,
    image_path TEXT,
    used_at TEXT NOT NULL
)
"""

_CREATE_PRESETS_TABLE = """
CREATE TABLE IF NOT EXISTS presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    settings TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_PLATFORM_CONNECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS platform_connections (
    platform TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TEXT,
    user_handle TEXT,
    user_avatar TEXT,
    extra TEXT,
    connected_at TEXT NOT NULL
)
"""

_CREATE_PUBLISH_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS publish_log (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    platform_post_id TEXT,
    platform_url TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_BRAND_KITS_TABLE = """
CREATE TABLE IF NOT EXISTS brand_kits (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    logo_path TEXT,
    watermark_position TEXT NOT NULL DEFAULT 'br',
    subtitle_font_size INTEGER NOT NULL DEFAULT 24,
    subtitle_color TEXT NOT NULL DEFAULT '#ffffff',
    subtitle_bg TEXT NOT NULL DEFAULT 'shadow',
    subtitle_position TEXT NOT NULL DEFAULT 'bottom',
    default_format TEXT NOT NULL DEFAULT 'mp4',
    output_subfolder TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


async def init_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_JOBS_TABLE)
        await db.execute(_CREATE_WATERMARK_HISTORY_TABLE)
        await db.execute(_CREATE_PRESETS_TABLE)
        await db.execute(_CREATE_PLATFORM_CONNECTIONS_TABLE)
        await db.execute(_CREATE_PUBLISH_LOG_TABLE)
        await db.execute(_CREATE_BRAND_KITS_TABLE)
        await db.commit()


def _row_to_job(row: aiosqlite.Row) -> ClipJob:
    def _dt(val: str | None) -> datetime | None:
        if not val:
            return None
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    return ClipJob(
        id=row[0],
        status=JobStatus(row[1]),
        url=row[2],
        video_title=row[3],
        start_time=row[4],
        end_time=row[5],
        output_format=OutputFormat(row[6]),
        include_subtitles=bool(row[7]),
        quality=row[8],
        output_path=row[9],
        output_filename=row[10],
        error_message=row[11],
        progress=row[12],
        created_at=_dt(row[13]),
        updated_at=_dt(row[14]),
        completed_at=_dt(row[15]),
    )


async def insert_job(db_path: Path, job: ClipJob) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO jobs
              (id, status, url, video_title, start_time, end_time, output_format,
               include_subtitles, quality, output_path, output_filename,
               error_message, progress, created_at, updated_at, completed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.id, job.status.value, job.url, job.video_title,
                job.start_time, job.end_time, job.output_format.value,
                int(job.include_subtitles), job.quality,
                job.output_path, job.output_filename, job.error_message,
                job.progress, now, now, None,
            ),
        )
        await db.commit()


async def update_job_status(
    db_path: Path,
    job_id: str,
    status: JobStatus,
    progress: float | None = None,
    error_message: str | None = None,
    output_path: str | None = None,
    output_filename: str | None = None,
    video_title: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    completed_at = now if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) else None

    fields = ["status = ?", "updated_at = ?"]
    values: list = [status.value, now]

    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if output_path is not None:
        fields.append("output_path = ?")
        values.append(output_path)
    if output_filename is not None:
        fields.append("output_filename = ?")
        values.append(output_filename)
    if video_title is not None:
        fields.append("video_title = ?")
        values.append(video_title)
    if completed_at is not None:
        fields.append("completed_at = ?")
        values.append(completed_at)

    values.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"

    async with aiosqlite.connect(db_path) as db:
        await db.execute(sql, values)
        await db.commit()


async def get_job(db_path: Path, job_id: str) -> ClipJob | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_job(row) if row else None


async def list_jobs(db_path: Path, limit: int = 50, offset: int = 0) -> list[ClipJob]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_job(r) for r in rows]


async def list_completed_jobs(db_path: Path, limit: int = 50, offset: int = 0) -> list[ClipJob]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT * FROM jobs WHERE status = 'completed' ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_job(r) for r in rows]


async def delete_job(db_path: Path, job_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await db.commit()
        return cursor.rowcount > 0


# ── Watermark history ────────────────────────────────────────────────────────

async def save_watermark(
    db_path: Path,
    wm_type: str,
    value: str,
    image_path: str | None = None,
    max_history: int = 5,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    wm_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        # avoid duplicate text entries
        if wm_type == "text":
            await db.execute("DELETE FROM watermark_history WHERE type='text' AND value=?", (value,))
        await db.execute(
            "INSERT INTO watermark_history (id, type, value, image_path, used_at) VALUES (?,?,?,?,?)",
            (wm_id, wm_type, value, image_path, now),
        )
        # prune oldest beyond limit
        await db.execute(
            """DELETE FROM watermark_history WHERE id NOT IN (
                SELECT id FROM watermark_history ORDER BY used_at DESC LIMIT ?
            )""",
            (max_history,),
        )
        await db.commit()


async def list_watermark_history(db_path: Path) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, type, value, image_path, used_at FROM watermark_history ORDER BY used_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {"id": r[0], "type": r[1], "value": r[2], "image_path": r[3], "used_at": r[4]}
                for r in rows
            ]


async def delete_watermark(db_path: Path, wm_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM watermark_history WHERE id=?", (wm_id,))
        await db.commit()
        return cursor.rowcount > 0


# ── Presets ──────────────────────────────────────────────────────────────────

async def list_presets(db_path: Path) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, name, settings, created_at FROM presets ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {"id": r[0], "name": r[1], "settings": json.loads(r[2]), "created_at": r[3]}
                for r in rows
            ]


async def save_preset(db_path: Path, name: str, settings: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    preset_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO presets (id, name, settings, created_at) VALUES (?,?,?,?)",
            (preset_id, name, json.dumps(settings), now),
        )
        await db.commit()
    return {"id": preset_id, "name": name, "settings": settings, "created_at": now}


async def delete_preset(db_path: Path, preset_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM presets WHERE id=?", (preset_id,))
        await db.commit()
        return cursor.rowcount > 0


# ── Platform connections ──────────────────────────────────────────────────────

def _row_to_connection(row) -> dict:
    return {
        "platform": row[0],
        "access_token": row[1],
        "refresh_token": row[2],
        "expires_at": row[3],
        "user_handle": row[4],
        "user_avatar": row[5],
        "extra": json.loads(row[6]) if row[6] else {},
        "connected_at": row[7],
    }


async def list_platform_connections(db_path: Path) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT platform, access_token, refresh_token, expires_at, user_handle, user_avatar, extra, connected_at FROM platform_connections"
        ) as cur:
            return [_row_to_connection(r) for r in await cur.fetchall()]


async def get_platform_connection(db_path: Path, platform: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT platform, access_token, refresh_token, expires_at, user_handle, user_avatar, extra, connected_at FROM platform_connections WHERE platform=?",
            (platform,),
        ) as cur:
            row = await cur.fetchone()
            return _row_to_connection(row) if row else None


async def save_platform_connection(
    db_path: Path,
    platform: str,
    access_token: str,
    refresh_token: str = "",
    expires_at: str = "",
    user_handle: str = "",
    user_avatar: str = "",
    extra: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR REPLACE INTO platform_connections
               (platform, access_token, refresh_token, expires_at, user_handle, user_avatar, extra, connected_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (platform, access_token, refresh_token or "", expires_at or "", user_handle or "", user_avatar or "", json.dumps(extra or {}), now),
        )
        await db.commit()


async def delete_platform_connection(db_path: Path, platform: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM platform_connections WHERE platform=?", (platform,))
        await db.commit()
        return cursor.rowcount > 0


# ── Publish log ───────────────────────────────────────────────────────────────

async def create_publish_log(db_path: Path, job_id: str, platform: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    log_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO publish_log (id, job_id, platform, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (log_id, job_id, platform, "pending", now, now),
        )
        await db.commit()
    return {"id": log_id, "job_id": job_id, "platform": platform, "status": "pending", "platform_url": None, "error": None, "created_at": now}


async def update_publish_log(
    db_path: Path,
    log_id: str,
    status: str,
    platform_url: str | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    fields = ["status = ?", "updated_at = ?"]
    values: list = [status, now]
    if platform_url is not None:
        fields.append("platform_url = ?")
        values.append(platform_url)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    values.append(log_id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(f"UPDATE publish_log SET {', '.join(fields)} WHERE id = ?", values)
        await db.commit()


async def list_publish_log(db_path: Path, job_id: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, job_id, platform, status, platform_url, error, created_at FROM publish_log WHERE job_id=? ORDER BY created_at DESC",
            (job_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {"id": r[0], "job_id": r[1], "platform": r[2], "status": r[3], "platform_url": r[4], "error": r[5], "created_at": r[6]}
                for r in rows
            ]


# ── Brand kits ────────────────────────────────────────────────────────────────

def _row_to_brand_kit(row) -> dict:
    return {
        "id": row[0], "name": row[1], "logo_path": row[2],
        "watermark_position": row[3], "subtitle_font_size": row[4],
        "subtitle_color": row[5], "subtitle_bg": row[6], "subtitle_position": row[7],
        "default_format": row[8], "output_subfolder": row[9], "created_at": row[10],
    }


async def list_brand_kits(db_path: Path) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id,name,logo_path,watermark_position,subtitle_font_size,subtitle_color,subtitle_bg,subtitle_position,default_format,output_subfolder,created_at FROM brand_kits ORDER BY created_at DESC"
        ) as cur:
            return [_row_to_brand_kit(r) for r in await cur.fetchall()]


async def get_brand_kit(db_path: Path, kit_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id,name,logo_path,watermark_position,subtitle_font_size,subtitle_color,subtitle_bg,subtitle_position,default_format,output_subfolder,created_at FROM brand_kits WHERE id=?",
            (kit_id,),
        ) as cur:
            row = await cur.fetchone()
            return _row_to_brand_kit(row) if row else None


async def save_brand_kit(
    db_path: Path,
    name: str,
    logo_path: str | None = None,
    watermark_position: str = "br",
    subtitle_font_size: int = 24,
    subtitle_color: str = "#ffffff",
    subtitle_bg: str = "shadow",
    subtitle_position: str = "bottom",
    default_format: str = "mp4",
    output_subfolder: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    kit_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR REPLACE INTO brand_kits
               (id,name,logo_path,watermark_position,subtitle_font_size,subtitle_color,subtitle_bg,subtitle_position,default_format,output_subfolder,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (kit_id, name, logo_path, watermark_position, subtitle_font_size, subtitle_color, subtitle_bg, subtitle_position, default_format, output_subfolder, now),
        )
        await db.commit()
    return {
        "id": kit_id, "name": name, "logo_path": logo_path,
        "watermark_position": watermark_position, "subtitle_font_size": subtitle_font_size,
        "subtitle_color": subtitle_color, "subtitle_bg": subtitle_bg, "subtitle_position": subtitle_position,
        "default_format": default_format, "output_subfolder": output_subfolder, "created_at": now,
    }


async def delete_brand_kit(db_path: Path, kit_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM brand_kits WHERE id=?", (kit_id,))
        await db.commit()
        return cursor.rowcount > 0
