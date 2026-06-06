from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...config import Config, get_config
from ...database import list_completed_jobs
from ...models import format_time

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/library")
async def library(
    request: Request,
    page: int = 1,
    config: Config = Depends(get_config),
):
    per_page = 20
    offset = (page - 1) * per_page
    jobs = await list_completed_jobs(config.db_path, limit=per_page + 1, offset=offset)

    has_next = len(jobs) > per_page
    jobs = jobs[:per_page]

    # Annotate with file existence and human-readable duration
    enriched = []
    for job in jobs:
        exists = bool(job.output_path and Path(job.output_path).exists())
        duration = format_time(job.end_time - job.start_time) if job.end_time and job.start_time else "—"
        enriched.append({"job": job, "file_exists": exists, "duration": duration})

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "clips": enriched,
            "page": page,
            "has_next": has_next,
            "has_prev": page > 1,
        },
    )
