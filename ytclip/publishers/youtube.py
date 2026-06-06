from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .base import Publisher

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubePublisher(Publisher):
    name = "youtube"
    display_name = "YouTube Shorts"
    icon = "fa-brands fa-youtube"
    color = "#ff0000"

    def auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(_TOKEN_URL, data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            tokens = r.json()

        info = await self._channel_info(tokens["access_token"])
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
        ).isoformat()

        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": expires_at,
            "user_handle": info.get("handle", ""),
            "user_avatar": info.get("avatar", ""),
            "extra": {},
        }

    async def _channel_info(self, token: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                _CHANNELS_URL,
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.is_success:
                items = r.json().get("items", [])
                if items:
                    s = items[0]["snippet"]
                    return {
                        "handle": s.get("customUrl") or s.get("title", ""),
                        "avatar": s.get("thumbnails", {}).get("default", {}).get("url", ""),
                    }
        return {}

    async def refresh(self, connection: dict) -> dict:
        rt = connection.get("refresh_token")
        if not rt:
            return connection
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(_TOKEN_URL, data={
                "refresh_token": rt,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            })
            r.raise_for_status()
            tokens = r.json()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
        ).isoformat()
        connection["access_token"] = tokens["access_token"]
        connection["expires_at"] = expires_at
        return connection

    async def upload(
        self,
        connection: dict,
        path: Path,
        title: str,
        description: str = "",
        privacy: str = "public",
        **kwargs,
    ) -> str:
        connection = await self._maybe_refresh(connection)
        token = connection["access_token"]
        size = path.stat().st_size

        body = {
            "snippet": {
                "title": title[:100],
                "description": (f"{description}\n\n#Shorts" if description else "#Shorts"),
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        # Initiate resumable upload
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                _UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/*",
                    "X-Upload-Content-Length": str(size),
                },
                content=json.dumps(body).encode(),
            )
            r.raise_for_status()
            upload_url = r.headers["Location"]

        # Upload file bytes
        async with httpx.AsyncClient(timeout=600) as client:
            with open(path, "rb") as f:
                data = f.read()
            r2 = await client.put(
                upload_url,
                content=data,
                headers={"Content-Type": "video/*", "Content-Length": str(size)},
            )
            r2.raise_for_status()
            video_id = r2.json()["id"]

        return f"https://www.youtube.com/shorts/{video_id}"
