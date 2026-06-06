from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from ...config import Config, get_config
from ...clipper import create_clip
from ...database import delete_job, get_job, insert_job, save_watermark, update_job_status
from ...jobs import JobRunner, get_job_runner, get_progress_bus
from ...models import ClipJob, JobStatus, OutputFormat, parse_time, format_time

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.post("", response_class=HTMLResponse)
async def create_clip_job(
    request: Request,
    url: Annotated[str, Form()],
    start_time: Annotated[str, Form()],
    end_time: Annotated[str, Form()],
    output_format: Annotated[str, Form()] = "mp4",
    include_subtitles: Annotated[bool, Form()] = False,
    crop_x: Annotated[float | None, Form()] = None,
    crop_y: Annotated[float | None, Form()] = None,
    crop_w: Annotated[float | None, Form()] = None,
    crop_h: Annotated[float | None, Form()] = None,
    speed: Annotated[float, Form()] = 1.0,
    watermark_text: Annotated[str, Form()] = "",
    watermark_position: Annotated[str, Form()] = "br",
    watermark_image: Annotated[UploadFile | None, File()] = None,
    watermark_image_path: Annotated[str, Form()] = "",
    subtitle_font_size: Annotated[int, Form()] = 24,
    subtitle_color: Annotated[str, Form()] = "#ffffff",
    subtitle_bg: Annotated[str, Form()] = "shadow",
    subtitle_position: Annotated[str, Form()] = "bottom",
    config: Config = Depends(get_config),
    runner: JobRunner = Depends(get_job_runner),
):
    try:
        start_s = parse_time(start_time)
        end_s = parse_time(end_time)
    except ValueError as exc:
        return HTMLResponse(f'<div class="alert alert-error">{exc}</div>')

    if start_s >= end_s:
        return HTMLResponse('<div class="alert alert-error">Start time must be before end time.</div>')

    if config.general.max_clip_duration > 0 and (end_s - start_s) > config.general.max_clip_duration:
        limit = format_time(config.general.max_clip_duration)
        return HTMLResponse(f'<div class="alert alert-error">Clip duration exceeds the configured limit of {limit}.</div>')

    try:
        fmt = OutputFormat(output_format)
    except ValueError:
        fmt = OutputFormat.MP4

    crop: dict | None = None
    if all(v is not None for v in (crop_x, crop_y, crop_w, crop_h)):
        crop = {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}

    wm_image_path: Path | None = None
    wm_tmp_dir: str | None = None
    _saved_wm_image_path: str | None = None

    if watermark_image and watermark_image.filename:
        wm_tmp_dir = tempfile.mkdtemp(prefix="ytclip_wm_")
        suffix = Path(watermark_image.filename).suffix or ".png"
        wm_image_path = Path(wm_tmp_dir) / f"watermark{suffix}"
        with open(wm_image_path, "wb") as fh:
            shutil.copyfileobj(watermark_image.file, fh)
        # persist to watermarks store
        wm_store_dir = config.db_path.parent / "watermarks"
        wm_store_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex[:8]}_{watermark_image.filename}"
        stored_path = wm_store_dir / stored_name
        shutil.copy2(wm_image_path, stored_path)
        _saved_wm_image_path = str(stored_path)
    elif watermark_image_path:
        p = Path(watermark_image_path)
        if p.exists():
            wm_image_path = p

    if watermark_text.strip():
        await save_watermark(config.db_path, "text", watermark_text.strip())
    if _saved_wm_image_path and watermark_image and watermark_image.filename:
        await save_watermark(
            config.db_path, "image",
            watermark_image.filename,
            image_path=_saved_wm_image_path,
        )

    subtitle_style = {
        "font_size": subtitle_font_size,
        "color": subtitle_color,
        "bg": subtitle_bg,
        "position": subtitle_position,
    }

    job = ClipJob(
        id=str(uuid.uuid4()),
        url=url.strip(),
        start_time=start_s,
        end_time=end_s,
        output_format=fmt,
        include_subtitles=include_subtitles,
        quality=config.quality.max_quality,
    )

    await insert_job(config.db_path, job)

    bus = get_progress_bus()
    loop = asyncio.get_event_loop()

    async def run_job():
        await update_job_status(config.db_path, job.id, JobStatus.IN_PROGRESS, progress=0)
        await bus.publish(job.id, {"type": "progress", "percent": 0, "message": "Starting..."})

        def progress_cb(pct: float, msg: str) -> None:
            bus.publish_sync(job.id, {"type": "progress", "percent": pct, "message": msg}, loop)

        try:
            try:
                output_path, video_title = await create_clip(
                    job_id=job.id,
                    url=job.url,
                    start_time=job.start_time,
                    end_time=job.end_time,
                    output_format=job.output_format,
                    quality=job.quality,
                    include_subtitles=job.include_subtitles,
                    output_dir=config.general.output_dir,
                    filename_template=config.output.filename_template,
                    cookies_file=config.ytdlp.cookies_file,
                    prefer_segments_only=config.quality.prefer_segments_only,
                    crop=crop,
                    speed=speed,
                    watermark_text=watermark_text,
                    watermark_image=wm_image_path,
                    watermark_position=watermark_position,
                    subtitle_style=subtitle_style,
                    progress_cb=progress_cb,
                )
            finally:
                if wm_tmp_dir:
                    shutil.rmtree(wm_tmp_dir, ignore_errors=True)

            await update_job_status(
                config.db_path, job.id, JobStatus.COMPLETED,
                progress=100,
                output_path=str(output_path),
                output_filename=output_path.name,
                video_title=video_title,
            )
            await bus.publish(job.id, {
                "type": "complete",
                "percent": 100,
                "message": "Done!",
                "filename": output_path.name,
            })

        except Exception as exc:
            logger.error(f"Job {job.id} failed: {exc}", exc_info=True)
            await update_job_status(
                config.db_path, job.id, JobStatus.FAILED,
                error_message=str(exc),
            )
            await bus.publish(job.id, {
                "type": "error",
                "percent": 0,
                "message": str(exc),
            })

    await runner.submit(job.id, run_job())

    return templates.TemplateResponse(
        request,
        "partials/job_row.html",
        {
            "job": job,
            "start_fmt": format_time(job.start_time),
            "end_fmt": format_time(job.end_time),
        },
    )


@router.get("/{job_id}/progress")
async def job_progress(job_id: str, request: Request):
    bus = get_progress_bus()

    async def generator():
        queue = bus.subscribe(job_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue

                yield {"event": "message", "data": _render_progress(job_id, event)}

                if event.get("type") in ("complete", "error"):
                    break
        finally:
            bus.unsubscribe(job_id, queue)

    return EventSourceResponse(generator())


def _render_progress(job_id: str, event: dict) -> str:
    pct = event.get("percent", 0)
    msg = event.get("message", "")
    typ = event.get("type", "progress")

    if typ == "complete":
        filename = event.get("filename", "clip")
        return (
            f'<div class="job-done">'
            f'<div class="job-done-left">'
            f'<div class="job-done-icon"><i class="fa-solid fa-check"></i></div>'
            f'<span class="job-done-filename">{filename}</span>'
            f'</div>'
            f'<a class="btn-download" href="/clips/{job_id}/download" download="{filename}">'
            f'<i class="fa-solid fa-download"></i> Download'
            f'</a>'
            f'</div>'
        )
    elif typ == "error":
        return (
            f'<div class="job-error">'
            f'<i class="fa-solid fa-circle-xmark"></i>'
            f'<span>{msg}</span>'
            f'</div>'
        )
    else:
        return (
            f'<div class="job-progress-bar">'
            f'<div class="job-progress-fill" style="width: {pct:.0f}%"></div>'
            f'</div>'
            f'<span class="job-progress-label">{msg} ({pct:.0f}%)</span>'
        )


@router.get("/{job_id}/download")
async def download_clip(
    job_id: str,
    config: Config = Depends(get_config),
):
    job = await get_job(config.db_path, job_id)
    if not job or job.status != JobStatus.COMPLETED or not job.output_path:
        return HTMLResponse('<div class="alert alert-error">Clip not found or not ready.</div>', status_code=404)

    output_path = Path(job.output_path)
    if not output_path.exists():
        return HTMLResponse('<div class="alert alert-error">File no longer exists on disk.</div>', status_code=404)

    return FileResponse(
        path=str(output_path),
        filename=job.output_filename or output_path.name,
        media_type="application/octet-stream",
    )


@router.delete("/{job_id}", response_class=HTMLResponse)
async def delete_clip(
    job_id: str,
    config: Config = Depends(get_config),
):
    job = await get_job(config.db_path, job_id)
    if job and job.output_path:
        p = Path(job.output_path)
        p.unlink(missing_ok=True)

    await delete_job(config.db_path, job_id)
    return HTMLResponse("")
