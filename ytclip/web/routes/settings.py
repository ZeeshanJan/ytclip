from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from ...config import Config, get_config
from ...database import list_brand_kits, list_platform_connections
from ...publishers import PUBLISHERS

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/settings")
async def settings_page(
    request: Request,
    config: Config = Depends(get_config),
    connected: str | None = None,
    error: str | None = None,
):
    existing = {c["platform"]: c for c in await list_platform_connections(config.db_path)}
    brand_kits = await list_brand_kits(config.db_path)

    platforms = []
    for platform, cls in PUBLISHERS.items():
        inst = cls("", "", "")
        pc = getattr(config.platforms, platform, None)
        configured = bool(pc and pc.client_id and pc.client_secret)
        conn = existing.get(platform)
        platforms.append({
            "name": platform,
            "display_name": inst.display_name,
            "icon": inst.icon,
            "color": inst.color,
            "configured": configured,
            "connected": conn is not None,
            "user_handle": conn["user_handle"] if conn else None,
            "user_avatar": conn["user_avatar"] if conn else None,
        })

    return templates.TemplateResponse(request, "settings.html", {
        "platforms": platforms,
        "brand_kits": brand_kits,
        "flash_connected": connected,
        "flash_error": error,
    })
