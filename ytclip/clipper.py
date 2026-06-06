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

    # GIF/WEBP download as best video quality; conversion happens in post-filter pass
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
    elif output_format in (OutputFormat.GIF, OutputFormat.WEBP):
        # Trim as MP4 first; _apply_video_filters handles GIF/WebP conversion
        codec_args = ["-c", "copy", "-movflags", "+faststart"]
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


def _atempo_chain(speed: float) -> str:
    """Build atempo filter chain — atempo is limited to 0.5–2.0 per filter."""
    if abs(speed - 1.0) < 0.001:
        return ""
    parts: list[str] = []
    s = speed
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def _crop_filter(crop: dict) -> str:
    return (
        f"crop=floor(iw*{crop['w']}/2)*2"
        f":floor(ih*{crop['h']}/2)*2"
        f":floor(iw*{crop['x']}/2)*2"
        f":floor(ih*{crop['y']}/2)*2"
    )


_OVERLAY_POS = {
    "br": ("main_w-overlay_w-10", "main_h-overlay_h-10"),
    "bl": ("10",                   "main_h-overlay_h-10"),
    "tr": ("main_w-overlay_w-10", "10"),
    "tl": ("10",                   "10"),
}
_TEXT_POS = {
    "br": ("W-tw-10", "H-th-10"),
    "bl": ("10",       "H-th-10"),
    "tr": ("W-tw-10", "10"),
    "tl": ("10",       "10"),
}


async def _run_ffmpeg(cmd: list[str], label: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{label}: {stderr.decode()[-600:]}")


async def _encode_gif(
    input_file: Path,
    output_file: Path,
    vf_chain: list[str],
    watermark_text: str,
    wm_pos: str,
) -> Path:
    """Two-pass GIF with palette optimisation. Text watermark supported."""
    vf = ",".join(vf_chain) if vf_chain else "null"
    if watermark_text.strip():
        tx, ty = _TEXT_POS.get(wm_pos, _TEXT_POS["br"])
        safe = watermark_text.strip().replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        vf += f",drawtext=text='{safe}':x={tx}:y={ty}:fontsize=28:fontcolor=white@0.85:shadowcolor=black@0.5:shadowx=1:shadowy=1"

    palette = output_file.with_suffix(".palette.png")
    try:
        await _run_ffmpeg([
            "ffmpeg", "-y", "-i", str(input_file),
            "-vf", f"{vf},palettegen=max_colors=256:stats_mode=diff",
            str(palette),
        ], "GIF palettegen")
        await _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(input_file), "-i", str(palette),
            "-filter_complex", f"[0:v]{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
            "-an", str(output_file),
        ], "GIF encode")
    finally:
        palette.unlink(missing_ok=True)
    return output_file


async def _apply_video_filters(
    input_file: Path,
    output_file: Path,
    output_format: OutputFormat,
    crop: dict | None = None,
    speed: float = 1.0,
    watermark_text: str = "",
    watermark_image: Path | None = None,
    watermark_position: str = "br",
) -> Path:
    """Apply crop, speed, watermark, and format conversion in a single ffmpeg pass."""
    is_gif  = output_format == OutputFormat.GIF
    is_webp = output_format == OutputFormat.WEBP
    has_img = bool(watermark_image and watermark_image.exists()) and not is_gif
    has_txt = bool(watermark_text.strip())

    vf: list[str] = []
    if crop:
        vf.append(_crop_filter(crop))
    if abs(speed - 1.0) > 0.001:
        vf.append(f"setpts={1.0 / speed:.6f}*PTS")
    if is_gif:
        vf.extend(["fps=15", "scale=480:-2:flags=lanczos"])
    elif is_webp:
        vf.extend(["fps=24", "scale=720:-2:flags=lanczos"])

    if is_gif:
        return await _encode_gif(input_file, output_file, vf, watermark_text, watermark_position)

    ox, oy = _OVERLAY_POS.get(watermark_position, _OVERLAY_POS["br"])
    tx, ty = _TEXT_POS.get(watermark_position, _TEXT_POS["br"])
    safe_txt = watermark_text.strip().replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:") if has_txt else ""
    txt_filter = (
        f"drawtext=text='{safe_txt}':x={tx}:y={ty}"
        f":fontsize=28:fontcolor=white@0.85:shadowcolor=black@0.5:shadowx=1:shadowy=1"
    ) if has_txt else ""

    # Build filter section
    extra_inputs: list[str] = []
    filter_section: list[str] = []

    if has_img:
        extra_inputs = ["-i", str(watermark_image)]
        base = ",".join(vf) if vf else "null"
        suffix = f",{txt_filter}" if has_txt else ""
        fc = f"[0:v]{base}[base];[1:v]scale=iw/6:-1[wm];[base][wm]overlay={ox}:{oy}{suffix}[out]"
        filter_section = ["-filter_complex", fc, "-map", "[out]", "-map", "0:a?"]
    elif has_txt:
        vf.append(txt_filter)
        filter_section = ["-vf", ",".join(vf)]
    elif vf:
        filter_section = ["-vf", ",".join(vf)]

    # Audio
    if is_webp:
        audio_args: list[str] = ["-an"]
    else:
        audio_args = ["-c:a", "aac", "-b:a", "192k"]
        chain = _atempo_chain(speed)
        if chain:
            audio_args = ["-af", chain] + audio_args

    # Video codec
    if is_webp:
        codec_args = ["-vcodec", "libwebp", "-lossless", "0", "-quality", "80", "-loop", "0"]
    else:
        codec_args = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-movflags", "+faststart"]

    await _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", str(input_file),
        *extra_inputs,
        *filter_section,
        *codec_args,
        *audio_args,
        str(output_file),
    ], "video filters")
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
    crop: dict | None = None,
    speed: float = 1.0,
    watermark_text: str = "",
    watermark_image: Path | None = None,
    watermark_position: str = "br",
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
        elif output_format in (OutputFormat.MP4, OutputFormat.GIF, OutputFormat.WEBP):
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

        needs_filter = (
            crop is not None
            or abs(speed - 1.0) > 0.001
            or bool(watermark_text)
            or (watermark_image is not None and watermark_image.exists())
            or output_format in (OutputFormat.GIF, OutputFormat.WEBP)
        )

        if needs_filter:
            progress_cb(85, "Applying filters...")
            out_ext = output_format.value if output_format in (OutputFormat.GIF, OutputFormat.WEBP) else "mp4"
            filtered_file = tmp_dir / f"filtered.{out_ext}"
            downloaded_file = await _apply_video_filters(
                downloaded_file,
                filtered_file,
                output_format,
                crop=crop,
                speed=speed,
                watermark_text=watermark_text,
                watermark_image=watermark_image,
                watermark_position=watermark_position,
            )

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
