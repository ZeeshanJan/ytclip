from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..clipper import setup_ffmpeg
from ..config import Config, get_config
from ..database import init_db
from ..jobs import init_job_runner, get_job_runner
from ..updater import maybe_update_ytdlp
from .auth import make_login_router, require_auth
from .routes.clips import router as clips_router
from .routes.library import router as library_router
from .routes.video import router as video_router

_WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def _configure_logging(config: Config) -> None:
    log_level = getattr(logging, config.general.log_level, logging.INFO)
    handlers = [logging.StreamHandler()]
    if config.general.log_file:
        handlers.append(logging.FileHandler(config.general.log_file))
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def create_app(config: Config | None = None) -> FastAPI:
    if config is None:
        config = get_config()

    _configure_logging(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_ffmpeg()
        await init_db(config.db_path)
        runner = init_job_runner(config.general.max_concurrent_jobs)
        await runner.start()
        await maybe_update_ytdlp(
            config.ytdlp.auto_update_interval_hours,
            config.ytdlp.auto_update,
        )
        yield
        await runner.stop()

    app = FastAPI(
        title="ytclip",
        description="Self-hosted YouTube clip creator",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(_WEB_DIR / "static")),
        name="static",
    )

    # Auth routes (always available)
    if config.auth.enabled:
        app.include_router(make_login_router())

    # Protected routes
    dependencies = []
    if config.auth.enabled:
        from fastapi import Depends
        dependencies = [Depends(require_auth)]

    app.include_router(video_router, dependencies=dependencies)
    app.include_router(clips_router, dependencies=dependencies)
    app.include_router(library_router, dependencies=dependencies)

    @app.get("/")
    async def landing(request: Request):
        return templates.TemplateResponse(request, "landing.html")

    @app.get("/app")
    async def index(request: Request):
        if config.auth.enabled:
            from .auth import _is_authenticated
            if not _is_authenticated(request, config):
                return RedirectResponse("/login")
        return templates.TemplateResponse(request, "index.html")

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return templates.TemplateResponse(request, "landing.html", status_code=404)

    return app
