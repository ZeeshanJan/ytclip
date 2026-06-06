from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import yt_dlp

from .models import OutputFormat, generate_filename

logger = logging.getLogger(__name__)

_QUALITY_HEIGHT_MAP = {
    "2160p": 2160, "4k": 2160,
    "1440p": 1440, "2k": 1440,
    "1080p": 1080, "fhd": 1080,
    "720p": 720, "hd": 720,
    "480p": 480,
    "360p": 360,
}


def setup_ffmpeg() -> None:
    """Use system ffmpeg if available, otherwise fall back to static-ffmpeg bundle."""
    if shutil.which("ffmpeg") is None:
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
            logger.debug("Using bundled static-ffmpeg")
        except ImportError:
            logger.warning("static-ffmpeg not installed and no system ffmpeg found")
    else:
        logger.debug("Using system ffmpeg")


def _build_format_string(output_format: OutputFormat, max_quality: str) -> str:
    height = _QUALITY_HEIGHT_MAP.get(max_quality.lower())

    if output_format in (OutputFormat.MP3, OutputFormat.AAC):
        return "bestaudio/best"

    if height:
        return (
            f"bestvideo[height<={height}]+bestaudio"
            f"/best[height<={height}]/best"
        )
    return "bestvideo+bestaudio/best"


def _make_range_func(start: float, end: float) -> Callable:
    """Return a download_ranges-compatible function for yt-dlp."""
    def range_func(info_dict: dict, ydl: yt_dlp.YoutubeDL) -> list[dict]:
        return [{"start_time": start, "end_time": end}]
    return range_func


def _make_progress_hook(
    phase: str,
    phase_start_pct: float,
    phase_end_pct: float,
    progress_cb: Callable[[float, str], None],
    loop: asyncio.AbstractEventLoop,
) -> Callable:
    def hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                ratio = downloaded / total
                pct = phase_start_pct + ratio * (phase_end_pct - phase_start_pct)
                msg = f"{phase}: {ratio * 100:.0f}%"
                asyncio.run_coroutine_threadsafe(
                    _async_cb(progress_cb, pct, msg), loop
                )
        elif d["status"] == "finished":
            asyncio.run_coroutine_threadsafe(
                _async_cb(progress_cb, phase_end_pct, f"{phase}: done"), loop
            )
    return hook


async def _async_cb(cb: Callable, *args) -> None:
    cb(*args)


async def _trim_with_ffmpeg(
    input_file: Path,
    start_time: float,
    end_time: float,
    output_format: OutputFormat,
    output_file: Path,
) -> Path:
    """Fallback precise trim using ffmpeg when segment download isn't available."""
    if output_format == OutputFormat.MP3:
        codec_args = ["-vn", "-acodec", "libmp3lame", "-q:a", "0"]
    elif output_format == OutputFormat.AAC:
        codec_args = ["-vn", "-acodec", "copy"]
    elif output_format == OutputFormat.MKV:
        codec_args = ["-c", "copy"]
    else:
        # MP4: try stream copy; if fails we accept the error (caller retries with transcode)
        codec_args = ["-c", "copy", "-movflags", "+faststart"]

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", str(input_file),
        *codec_args,
        str(output_file),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        # Stream copy failed for MP4 — retry with transcode
        if output_format == OutputFormat.MP4:
            logger.debug("Stream copy failed, transcoding to MP4")
            cmd2 = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-to", str(end_time),
                "-i", str(input_file),
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_file),
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd2,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr2 = await proc2.communicate()
            if proc2.returncode != 0:
                raise RuntimeError(f"ffmpeg transcode failed: {stderr2.decode()[-500:]}")
        else:
            raise RuntimeError(f"ffmpeg failed: {stderr.decode()[-500:]}")

    return output_file


async def get_video_info(url: str, cookies_file: str = "") -> dict:
    """Fetch video metadata without downloading."""
    ydl_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    loop = asyncio.get_event_loop()

    def _fetch():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = await loop.run_in_executor(None, _fetch)
    return {
        "id": info.get("id"),
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
    }


async def create_clip(
    job_id: str,
    url: str,
    start_time: float,
    end_time: float,
    output_format: OutputFormat,
    quality: str,
    include_subtitles: bool,
    output_dir: Path,
    filename_template: str,
    cookies_file: str,
    prefer_segments_only: bool,
    progress_cb: Callable[[float, str], None],
) -> tuple[Path, str]:
    """
    Download and trim a YouTube clip.
    Returns (output_path, video_title).
    """
    loop = asyncio.get_event_loop()
    format_str = _build_format_string(output_format, quality)

    with tempfile.TemporaryDirectory(prefix="ytclip_") as tmp:
        tmp_dir = Path(tmp)

        base_opts: dict = {
            "format": format_str,
            "outtmpl": str(tmp_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [
                _make_progress_hook("Downloading", 0, 75, progress_cb, loop)
            ],
        }

        if cookies_file:
            base_opts["cookiefile"] = cookies_file

        if include_subtitles:
            base_opts["writesubtitles"] = True
            base_opts["subtitleslangs"] = ["en", "en-orig"]
            base_opts["embedsubtitles"] = True

        # Postprocessors for format conversion
        postprocessors: list[dict] = []
        if output_format == OutputFormat.MP3:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            })
        elif output_format == OutputFormat.AAC:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "aac",
                "preferredquality": "0",
            })
        elif output_format == OutputFormat.MKV:
            postprocessors.append({
                "key": "FFmpegVideoRemuxer",
                "when": "post_process",
                "preferedformat": "mkv",
            })
        elif output_format == OutputFormat.MP4:
            postprocessors.append({
                "key": "FFmpegVideoRemuxer",
                "when": "post_process",
                "preferedformat": "mp4",
            })

        if postprocessors:
            base_opts["postprocessors"] = postprocessors

        video_title = "Unknown"
        downloaded_file: Path | None = None

        # --- Attempt 1: segment-based download ---
        segment_opts = {
            **base_opts,
            "download_ranges": _make_range_func(start_time, end_time),
            "force_keyframes_at_cuts": True,
        }

        def _run_ydl(opts: dict) -> str | None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info.get("title") if info else None

        try:
            progress_cb(2, "Fetching video info...")
            title = await loop.run_in_executor(None, _run_ydl, segment_opts)
            if title:
                video_title = title

            files = [f for f in tmp_dir.iterdir() if f.is_file() and not f.name.endswith(".part")]
            if files:
                downloaded_file = max(files, key=lambda f: f.stat().st_size)
                logger.debug(f"Segment download succeeded: {downloaded_file.name}")
        except Exception as exc:
            if prefer_segments_only:
                raise RuntimeError(f"Segment download failed: {exc}") from exc
            logger.warning(f"Segment download failed, falling back to full download: {exc}")

        # --- Attempt 2: full download + ffmpeg trim ---
        if downloaded_file is None:
            progress_cb(5, "Downloading full stream...")
            try:
                title = await loop.run_in_executor(None, _run_ydl, base_opts)
                if title:
                    video_title = title

                files = [f for f in tmp_dir.iterdir() if f.is_file() and not f.name.endswith(".part")]
                if not files:
                    raise RuntimeError("No file downloaded from YouTube")

                source_file = max(files, key=lambda f: f.stat().st_size)
                progress_cb(80, "Trimming with ffmpeg...")

                ext = output_format.value
                trimmed = tmp_dir / f"trimmed.{ext}"
                downloaded_file = await _trim_with_ffmpeg(source_file, start_time, end_time, output_format, trimmed)
                source_file.unlink(missing_ok=True)
            except Exception as exc:
                raise RuntimeError(f"Download failed: {exc}") from exc

        progress_cb(90, "Saving clip...")

        # Determine final extension from downloaded file
        final_ext = downloaded_file.suffix.lstrip(".")
        filename = generate_filename(filename_template, video_title, start_time, end_time, job_id, final_ext)
        output_path = output_dir / filename

        # Handle filename collisions
        counter = 1
        stem = output_path.stem
        while output_path.exists():
            output_path = output_dir / f"{stem}_{counter}.{final_ext}"
            counter += 1

        shutil.move(str(downloaded_file), str(output_path))
        progress_cb(100, "Done")

        return output_path, video_title
