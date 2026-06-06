from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

from ...config import Config, get_config
from ...database import delete_watermark, list_watermark_history

router = APIRouter(prefix="/watermarks")


@router.get("/history")
async def watermark_history(config: Config = Depends(get_config)):
    return await list_watermark_history(config.db_path)


@router.delete("/history/{wm_id}", status_code=204)
async def remove_watermark(wm_id: str, config: Config = Depends(get_config)):
    await delete_watermark(config.db_path, wm_id)


@router.get("/history/{wm_id}/image")
async def watermark_image(wm_id: str, config: Config = Depends(get_config)):
    history = await list_watermark_history(config.db_path)
    entry = next((h for h in history if h["id"] == wm_id), None)
    if not entry or not entry["image_path"]:
        return HTMLResponse("Not found", status_code=404)
    p = Path(entry["image_path"])
    if not p.exists():
        return HTMLResponse("File not found", status_code=404)
    suffix = p.suffix.lower()
    media_types = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    return FileResponse(str(p), media_type=media_types.get(suffix, "image/png"))
