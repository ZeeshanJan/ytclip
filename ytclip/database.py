from __future__ import annotations

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


async def init_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_JOBS_TABLE)
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
