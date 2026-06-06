from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from ..config import Config, get_config

_SESSION_TOKEN = secrets.token_urlsafe(32)
_COOKIE_NAME = "ytclip_session"


def _is_authenticated(request: Request, config: Config) -> bool:
    if not config.auth.enabled:
        return True
    token = request.cookies.get(_COOKIE_NAME, "")
    return secrets.compare_digest(token, _SESSION_TOKEN)


async def require_auth(
    request: Request,
    config: Annotated[Config, Depends(get_config)],
) -> None:
    if not _is_authenticated(request, config):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": ""},
        )


def make_login_router():
    from fastapi import APIRouter
    from fastapi.templating import Jinja2Templates
    from pathlib import Path

    router = APIRouter()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @router.get("/login")
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @router.post("/login")
    async def do_login(
        request: Request,
        response: Response,
        password: str = Form(...),
        config: Config = Depends(get_config),
    ):
        if not config.auth.enabled:
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/", status_code=303)

        if secrets.compare_digest(password, config.auth.password):
            resp = Response(status_code=303, headers={"Location": "/"})
            resp.set_cookie(_COOKIE_NAME, _SESSION_TOKEN, httponly=True, samesite="lax")
            return resp

        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid password"},
            status_code=401,
        )

    @router.post("/logout")
    async def do_logout():
        resp = Response(status_code=303, headers={"Location": "/login"})
        resp.delete_cookie(_COOKIE_NAME)
        return resp

    return router
