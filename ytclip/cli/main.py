from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="ytclip",
    help="YouTube clip creator — self-hosted, quality-first.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback()
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        from .. import __version__
        console.print(f"\n[bold]ytclip[/bold] [dim]v{__version__}[/dim] — YouTube clip creator\n")
        console.print("  [cyan]ytclip serve[/cyan]      Start the web UI at [underline]http://localhost:8000[/underline]")
        console.print("  [cyan]ytclip clip[/cyan]       Create a clip from the command line")
        console.print("  [cyan]ytclip library[/cyan]    List saved clips")
        console.print("  [cyan]ytclip --help[/cyan]     Full command reference")
        console.print()
console = Console()


def _load_cfg(config_file: str | None):
    from ..config import load_config
    return load_config(config_file)


@app.command()
def clip(
    url: Annotated[str, typer.Argument(help="YouTube video URL")],
    end: Annotated[str, typer.Option("--end", "-e", help="End time (HH:MM:SS, MM:SS, or seconds)")],
    start: Annotated[str, typer.Option("--start", "-s", help="Start time (HH:MM:SS, MM:SS, or seconds)")] = "0",
    output_format: Annotated[str, typer.Option("--format", "-f", help="Output format: mp4 | mkv | mp3 | aac")] = "mp4",
    output_dir: Annotated[Optional[str], typer.Option("--output", "-o", help="Output directory")] = None,
    quality: Annotated[Optional[str], typer.Option("--quality", "-q", help="Max quality: best | 1080p | 720p | ...")] = None,
    subtitles: Annotated[bool, typer.Option("--subtitles", help="Include subtitles")] = False,
    config_file: Annotated[Optional[str], typer.Option("--config", "-c", help="Config file path")] = None,
    server_url: Annotated[Optional[str], typer.Option("--server-url", help="Delegate to a running ytclip server")] = None,
):
    """Create a clip from a YouTube video."""
    if server_url:
        _clip_via_server(server_url, url, start, end, output_format, subtitles)
        return

    cfg = _load_cfg(config_file)

    from ..models import parse_time, OutputFormat
    try:
        start_s = parse_time(start)
        end_s = parse_time(end)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if start_s >= end_s:
        console.print("[red]Error:[/red] Start time must be before end time.")
        raise typer.Exit(1)

    try:
        fmt = OutputFormat(output_format.lower())
    except ValueError:
        console.print(f"[red]Error:[/red] Unknown format '{output_format}'. Use: mp4, mkv, mp3, aac")
        raise typer.Exit(1)

    out_dir = Path(output_dir).expanduser() if output_dir else cfg.general.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    q = quality or cfg.quality.max_quality

    from ..clipper import setup_ffmpeg
    setup_ffmpeg()

    last_pct = [-1.0]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting...", total=100)

        def progress_cb(pct: float, msg: str) -> None:
            if pct > last_pct[0]:
                last_pct[0] = pct
                progress.update(task, completed=pct, description=msg)

        import uuid
        job_id = str(uuid.uuid4())

        try:
            output_path, title = asyncio.run(_run_clip(
                job_id=job_id,
                url=url,
                start_time=start_s,
                end_time=end_s,
                output_format=fmt,
                quality=q,
                include_subtitles=subtitles,
                output_dir=out_dir,
                filename_template=cfg.output.filename_template,
                cookies_file=cfg.ytdlp.cookies_file,
                prefer_segments_only=cfg.quality.prefer_segments_only,
                progress_cb=progress_cb,
            ))
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1)

    console.print(f"[green]✓[/green] Saved: [bold]{output_path}[/bold]")
    if title:
        console.print(f"  Title: {title}")


async def _run_clip(**kwargs):
    from ..clipper import create_clip
    return await create_clip(**kwargs)


def _clip_via_server(server_url: str, url: str, start: str, end: str, fmt: str, subtitles: bool) -> None:
    import httpx

    server_url = server_url.rstrip("/")
    console.print(f"Delegating to server: {server_url}")

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{server_url}/clips",
                data={
                    "url": url,
                    "start_time": start,
                    "end_time": end,
                    "output_format": fmt,
                    "include_subtitles": str(subtitles).lower(),
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            console.print("[green]✓[/green] Job submitted to server. Check the web UI for progress.")
    except Exception as exc:
        console.print(f"[red]Error:[/red] Could not reach server: {exc}")
        raise typer.Exit(1)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind host")] = None,
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port")] = None,
    config_file: Annotated[Optional[str], typer.Option("--config", "-c", help="Config file path")] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Enable auto-reload (dev mode)")] = False,
):
    """Start the ytclip web server."""
    import uvicorn
    from ..config import load_config

    cfg = load_config(config_file)
    h = host or cfg.server.host
    p = port or cfg.server.port

    console.print(f"[bold]ytclip[/bold] starting on [cyan]http://{h}:{p}[/cyan]")

    uvicorn.run(
        "ytclip.web.app:create_app",
        host=h,
        port=p,
        factory=True,
        reload=reload,
        log_level=cfg.general.log_level.lower(),
    )


@app.command()
def library(
    config_file: Annotated[Optional[str], typer.Option("--config", "-c", help="Config file path")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
):
    """List completed clips."""
    cfg = _load_cfg(config_file)

    clips = asyncio.run(_list_clips(cfg.db_path, limit))

    if not clips:
        console.print("[dim]No clips found.[/dim]")
        return

    from ..models import format_time
    table = Table(title="Clip Library", show_header=True, header_style="bold dim")
    table.add_column("Title", max_width=40, no_wrap=True)
    table.add_column("Duration", style="cyan")
    table.add_column("Format", style="dim")
    table.add_column("File")
    table.add_column("Created", style="dim")

    for job in clips:
        dur = format_time(job.end_time - job.start_time)
        exists = bool(job.output_path and Path(job.output_path).exists())
        file_str = f"[green]{job.output_filename}[/green]" if exists else f"[red]{job.output_filename} (missing)[/red]"
        created = job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else "—"
        table.add_row(job.video_title or "Unknown", dur, job.output_format.value.upper(), file_str, created)

    console.print(table)


async def _list_clips(db_path, limit):
    from ..database import list_completed_jobs
    return await list_completed_jobs(db_path, limit=limit)


@app.command()
def version():
    """Show version information."""
    from .. import __version__
    from ..updater import get_ytdlp_version
    import shutil

    console.print(f"ytclip {__version__}")
    console.print(f"yt-dlp  {get_ytdlp_version()}")
    ffmpeg = shutil.which("ffmpeg")
    console.print(f"ffmpeg  {'found at ' + ffmpeg if ffmpeg else 'not found (will use bundled)'}")
    console.print(f"python  {sys.version.split()[0]}")


if __name__ == "__main__":
    app()
