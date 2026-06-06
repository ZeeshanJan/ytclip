from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ...config import Config, get_config
from ...database import get_job
from ...models import JobStatus, format_time

router = APIRouter(prefix="/share")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/{job_id}")
async def share_page(job_id: str, request: Request, config: Config = Depends(get_config)):
    job = await get_job(config.db_path, job_id)
    if not job or job.status != JobStatus.COMPLETED or not job.output_path:
        return HTMLResponse("<h2>Clip not found or not ready.</h2>", status_code=404)

    output_path = Path(job.output_path)
    if not output_path.exists():
        return HTMLResponse("<h2>File no longer exists.</h2>", status_code=404)

    duration = format_time(job.end_time - job.start_time)
    base = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(
        request,
        "share.html",
        {
            "job": job,
            "duration": duration,
            "video_url": f"/share/{job_id}/video",
            "share_url": f"{base}/share/{job_id}",
        },
    )


@router.get("/{job_id}/video", name="share_video")
async def share_video(job_id: str, config: Config = Depends(get_config)):
    job = await get_job(config.db_path, job_id)
    if not job or job.status != JobStatus.COMPLETED or not job.output_path:
        return HTMLResponse("Not found", status_code=404)

    output_path = Path(job.output_path)
    if not output_path.exists():
        return HTMLResponse("File not found", status_code=404)

    suffix = output_path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska",
        ".gif": "image/gif", ".webp": "image/webp",
        ".mp3": "audio/mpeg", ".aac": "audio/aac",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(path=str(output_path), media_type=media_type)
