from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .base import Publisher

_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_USERINFO_URL = "https://open.tiktokapis.com/v2/user/info/"
_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

_PRIVACY = {
    "public": "PUBLIC_TO_EVERYONE",
    "friends": "MUTUAL_FOLLOW_FRIENDS",
    "private": "SELF_ONLY",
}


class TikTokPublisher(Publisher):
    name = "tiktok"
    display_name = "TikTok"
    icon = "fa-brands fa-tiktok"
    color = "#010101"

    def auth_url(self, state: str) -> str:
        params = {
            "client_key": self.client_id,
            "scope": "user.info.basic,video.publish,video.upload",
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                _TOKEN_URL,
                data={
                    "client_key": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            tokens = r.json().get("data", r.json())
            token = tokens["access_token"]

            r2 = await client.get(
                _USERINFO_URL,
                params={"fields": "open_id,display_name,avatar_url"},
                headers={"Authorization": f"Bearer {token}"},
            )
            user = r2.json().get("data", {}).get("user", {})

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 86400))
        ).isoformat()

        return {
            "access_token": token,
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": expires_at,
            "user_handle": user.get("display_name", ""),
            "user_avatar": user.get("avatar_url", ""),
            "extra": {"open_id": user.get("open_id", "")},
        }

    async def refresh(self, connection: dict) -> dict:
        rt = connection.get("refresh_token")
        if not rt:
            return connection
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                _TOKEN_URL,
                data={
                    "client_key": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": rt,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            tokens = r.json().get("data", r.json())
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 86400))
        ).isoformat()
        connection["access_token"] = tokens["access_token"]
        connection["expires_at"] = expires_at
        if tokens.get("refresh_token"):
            connection["refresh_token"] = tokens["refresh_token"]
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

        async with httpx.AsyncClient(timeout=600) as client:
            # Step 1: init upload
            r = await client.post(
                _INIT_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "post_info": {
                        "title": (description or title)[:150],
                        "privacy_level": _PRIVACY.get(privacy, "PUBLIC_TO_EVERYONE"),
                        "disable_comment": False,
                        "disable_duet": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": size,
                        "total_chunk_count": 1,
                    },
                },
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            publish_id = data["publish_id"]
            upload_url = data["upload_url"]

            # Step 2: upload chunk
            with open(path, "rb") as f:
                video_data = f.read()

            r2 = await client.put(
                upload_url,
                content=video_data,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size),
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                },
            )
            r2.raise_for_status()

            # Step 3: poll for completion
            _FAILED = {"FAILED", "SPAM_RISK_TOO_MANY_POSTS", "SPAM_RISK_USER_BANNED_FROM_POSTING"}
            for _ in range(30):
                await asyncio.sleep(5)
                r3 = await client.post(
                    _STATUS_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    json={"publish_id": publish_id},
                )
                status = r3.json().get("data", {}).get("status", "")
                if status == "PUBLISH_COMPLETE":
                    break
                if status in _FAILED:
                    raise RuntimeError(f"TikTok publish failed: {status}")

        # TikTok API does not return the post URL directly
        return "https://www.tiktok.com/profile"
