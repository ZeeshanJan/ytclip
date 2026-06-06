from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ...config import Config, get_config
from ...database import (
    create_publish_log,
    delete_platform_connection,
    get_job,
    get_platform_connection,
    list_platform_connections,
    list_publish_log,
    save_platform_connection,
    update_publish_log,
)
from ...publishers import PUBLISHERS

router = APIRouter(prefix="/publish")

# In-memory OAuth state store (single-user tool)
_states: dict[str, str] = {}


def _make_publisher(platform: str, config: Config):
    cls = PUBLISHERS.get(platform)
    if not cls:
        return None
    pc = getattr(config.platforms, platform, None)
    if not pc:
        return None
    redirect_uri = f"{config.public_url}/publish/callback/{platform}"
    return cls(pc.client_id, pc.client_secret, redirect_uri)


@router.get("/connections")
async def get_connections(config: Config = Depends(get_config)):
    existing = {c["platform"]: c for c in await list_platform_connections(config.db_path)}
    result = []
    for platform, cls in PUBLISHERS.items():
        inst = cls("", "", "")
        pc = getattr(config.platforms, platform, None)
        configured = bool(pc and pc.client_id and pc.client_secret)
        conn = existing.get(platform)
        result.append({
            "platform": platform,
            "display_name": inst.display_name,
            "icon": inst.icon,
            "color": inst.color,
            "configured": configured,
            "connected": conn is not None,
            "user_handle": conn["user_handle"] if conn else None,
            "user_avatar": conn["user_avatar"] if conn else None,
        })
    return result


@router.get("/connect/{platform}")
async def connect_platform(platform: str, config: Config = Depends(get_config)):
    pub = _make_publisher(platform, config)
    if not pub or not pub.is_configured:
        return HTMLResponse(f"Platform '{platform}' is not configured in config.toml.", status_code=400)
    state = secrets.token_urlsafe(16)
    _states[state] = platform
    return RedirectResponse(pub.auth_url(state))


@router.get("/callback/{platform}")
async def oauth_callback(
    platform: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    config: Config = Depends(get_config),
):
    if error:
        return RedirectResponse(f"/settings?error={error}")
    if not state or _states.get(state) != platform:
        return RedirectResponse("/settings?error=invalid_state")
    _states.pop(state, None)

    pub = _make_publisher(platform, config)
    if not pub:
        return RedirectResponse("/settings?error=not_configured")

    try:
        conn = await pub.exchange_code(code or "")
        await save_platform_connection(config.db_path, platform, **conn)
        return RedirectResponse(f"/settings?connected={platform}")
    except Exception as exc:
        return RedirectResponse(f"/settings?error={str(exc)[:120]}")


@router.delete("/disconnect/{platform}", status_code=204)
async def disconnect_platform(platform: str, config: Config = Depends(get_config)):
    await delete_platform_connection(config.db_path, platform)


@router.post("/{job_id}/{platform}")
async def publish_clip(
    job_id: str,
    platform: str,
    background_tasks: BackgroundTasks,
    title: str = "",
    description: str = "",
    privacy: str = "public",
    config: Config = Depends(get_config),
):
    job = await get_job(config.db_path, job_id)
    if not job or not job.output_path:
        return JSONResponse({"error": "Job not found or not completed."}, status_code=404)

    output_path = Path(job.output_path)
    if not output_path.exists():
        return JSONResponse({"error": "File not found on disk."}, status_code=404)

    conn = await get_platform_connection(config.db_path, platform)
    if not conn:
        return JSONResponse({"error": f"Not connected to {platform}."}, status_code=400)

    pub = _make_publisher(platform, config)
    if not pub:
        return JSONResponse({"error": f"Platform {platform} not configured."}, status_code=400)

    clip_title = title.strip() or job.video_title or output_path.stem
    log = await create_publish_log(config.db_path, job_id, platform)

    async def _do_upload() -> None:
        try:
            await update_publish_log(config.db_path, log["id"], "uploading")
            # Refresh token if needed and persist it back
            refreshed = await pub._maybe_refresh(conn)
            if refreshed.get("access_token") != conn.get("access_token"):
                await save_platform_connection(config.db_path, platform, **refreshed)
            url = await pub.upload(refreshed, output_path, clip_title, description, privacy)
            await update_publish_log(config.db_path, log["id"], "published", platform_url=url)
        except Exception as exc:
            await update_publish_log(config.db_path, log["id"], "failed", error=str(exc))

    background_tasks.add_task(_do_upload)
    return log


@router.get("/log/{job_id}")
async def get_log(job_id: str, config: Config = Depends(get_config)):
    return await list_publish_log(config.db_path, job_id)
