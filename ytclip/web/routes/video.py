from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import yt_dlp
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...config import Config, get_config
from ...models import extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _fetch_video_info(url: str) -> dict:
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "duration": float(info.get("duration") or 0),
                "title": info.get("title") or "",
                "playable_in_embed": info.get("playable_in_embed", True),
            }
    except Exception as exc:
        logger.debug("Could not fetch video info for %s: %s", url, exc)
        return {"duration": 0.0, "title": "", "playable_in_embed": True}


@router.post("/video-info", response_class=HTMLResponse)
async def video_info(
    request: Request,
    url: Annotated[str, Form()],
    config: Annotated[Config, Depends(get_config)],
):
    url = url.strip()
    video_id = extract_video_id(url)

    if not video_id:
        return HTMLResponse(
            '<div class="alert alert-error">Could not extract a YouTube video ID from that URL.</div>'
        )

    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _fetch_video_info, url)

    return templates.TemplateResponse(
        request,
        "partials/player.html",
        {
            "video_id": video_id,
            "url": url,
            "video_duration": info["duration"],
            "video_title": info["title"],
            "playable_in_embed": info["playable_in_embed"],
            "default_format": config.output.default_format,
            "include_subtitles": config.output.include_subtitles,
        },
    )
