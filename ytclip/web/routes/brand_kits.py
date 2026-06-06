from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ...config import Config, get_config
from ...database import delete_brand_kit, get_brand_kit, list_brand_kits, save_brand_kit

router = APIRouter(prefix="/brand-kits")


@router.get("")
async def get_brand_kits(config: Config = Depends(get_config)):
    return await list_brand_kits(config.db_path)


@router.post("", status_code=201)
async def create_brand_kit(
    name: Annotated[str, Form()],
    watermark_position: Annotated[str, Form()] = "br",
    subtitle_font_size: Annotated[int, Form()] = 24,
    subtitle_color: Annotated[str, Form()] = "#ffffff",
    subtitle_bg: Annotated[str, Form()] = "shadow",
    subtitle_position: Annotated[str, Form()] = "bottom",
    default_format: Annotated[str, Form()] = "mp4",
    output_subfolder: Annotated[str, Form()] = "",
    logo: Annotated[UploadFile | None, File()] = None,
    config: Config = Depends(get_config),
):
    logo_path: str | None = None
    if logo and logo.filename:
        logos_dir = config.data_dir / "brand_logos"
        logos_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(logo.filename).suffix or ".png"
        stored = logos_dir / f"{uuid.uuid4().hex}{suffix}"
        with open(stored, "wb") as f:
            shutil.copyfileobj(logo.file, f)
        logo_path = str(stored)

    return await save_brand_kit(
        config.db_path,
        name=name,
        logo_path=logo_path,
        watermark_position=watermark_position,
        subtitle_font_size=subtitle_font_size,
        subtitle_color=subtitle_color,
        subtitle_bg=subtitle_bg,
        subtitle_position=subtitle_position,
        default_format=default_format,
        output_subfolder=output_subfolder,
    )


@router.delete("/{kit_id}", status_code=204)
async def remove_brand_kit(kit_id: str, config: Config = Depends(get_config)):
    kit = await get_brand_kit(config.db_path, kit_id)
    if kit and kit.get("logo_path"):
        Path(kit["logo_path"]).unlink(missing_ok=True)
    await delete_brand_kit(config.db_path, kit_id)


@router.get("/{kit_id}/logo")
async def get_brand_logo(kit_id: str, config: Config = Depends(get_config)):
    kit = await get_brand_kit(config.db_path, kit_id)
    if not kit or not kit.get("logo_path"):
        return HTMLResponse("Not found", status_code=404)
    path = Path(kit["logo_path"])
    if not path.exists():
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(str(path))
