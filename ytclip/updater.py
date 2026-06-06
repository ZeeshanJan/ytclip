from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMESTAMP_FILE = Path.home() / ".ytclip" / "last_update_check.json"


def _read_last_check() -> datetime | None:
    try:
        data = json.loads(_TIMESTAMP_FILE.read_text())
        dt = datetime.fromisoformat(data["last_check"])
        # Ensure timezone-aware for comparison
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _write_last_check() -> None:
    _TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TIMESTAMP_FILE.write_text(json.dumps({"last_check": datetime.now(timezone.utc).isoformat()}))


def is_update_due(interval_hours: int) -> bool:
    last = _read_last_check()
    if last is None:
        return True
    return datetime.now(timezone.utc) - last > timedelta(hours=interval_hours)


def get_ytdlp_version() -> str:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return "unknown"


async def maybe_update_ytdlp(interval_hours: int, auto_update: bool) -> bool:
    """Check for yt-dlp updates. Returns True if an update was performed."""
    if not auto_update:
        return False
    if not is_update_due(interval_hours):
        return False

    import asyncio
    import sys

    logger.info("Checking for yt-dlp updates...")
    before = get_ytdlp_version()

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        _write_last_check()

        after = get_ytdlp_version()
        if before != after:
            logger.info(f"yt-dlp updated: {before} → {after}")
            return True
        else:
            logger.debug(f"yt-dlp already at latest: {after}")
            return False
    except Exception as exc:
        logger.warning(f"yt-dlp update check failed: {exc}")
        _write_last_check()
        return False
