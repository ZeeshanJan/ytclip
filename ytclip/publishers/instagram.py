from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .base import Publisher

_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_GRAPH = "https://graph.facebook.com/v19.0"
_SCOPES = "instagram_basic,instagram_content_publish,pages_show_list,business_management"


class InstagramPublisher(Publisher):
    name = "instagram"
    display_name = "Instagram Reels"
    icon = "fa-brands fa-instagram"
    color = "#e1306c"

    def auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": _SCOPES,
            "response_type": "code",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            # Short-lived token
            r = await client.get(_TOKEN_URL, params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "code": code,
            })
            r.raise_for_status()
            short_token = r.json()["access_token"]

            # Exchange for 60-day long-lived token
            r2 = await client.get(_TOKEN_URL, params={
                "grant_type": "fb_exchange_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "fb_exchange_token": short_token,
            })
            r2.raise_for_status()
            ll = r2.json()
            long_token = ll["access_token"]
            expires_in = ll.get("expires_in", 5183944)

            ig_user_id, handle, avatar = await self._get_ig_user(client, long_token)

        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

        return {
            "access_token": long_token,
            "refresh_token": "",
            "expires_at": expires_at,
            "user_handle": handle,
            "user_avatar": avatar,
            "extra": {"ig_user_id": ig_user_id},
        }

    async def _get_ig_user(self, client: httpx.AsyncClient, token: str):
        r = await client.get(f"{_GRAPH}/me/accounts", params={"access_token": token})
        for page in r.json().get("data", []):
            page_token = page["access_token"]
            r2 = await client.get(
                f"{_GRAPH}/{page['id']}",
                params={"fields": "instagram_business_account", "access_token": page_token},
            )
            ig = r2.json().get("instagram_business_account")
            if ig:
                ig_id = ig["id"]
                r3 = await client.get(
                    f"{_GRAPH}/{ig_id}",
                    params={"fields": "username,profile_picture_url", "access_token": token},
                )
                info = r3.json()
                return ig_id, info.get("username", ""), info.get("profile_picture_url", "")
        return "", "", ""

    async def refresh(self, connection: dict) -> dict:
        # Instagram long-lived tokens don't support refresh — re-auth when they expire
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
        token = connection["access_token"]
        ig_user_id = (connection.get("extra") or {}).get("ig_user_id", "")
        if not ig_user_id:
            raise ValueError("Instagram user ID not found — please reconnect.")

        size = path.stat().st_size
        caption = f"{description or title}\n\n#Reels"

        async with httpx.AsyncClient(timeout=600) as client:
            # Step 1: initiate resumable upload
            r = await client.post(
                f"{_GRAPH}/{ig_user_id}/media",
                params={"access_token": token},
                json={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": caption,
                },
            )
            r.raise_for_status()
            data = r.json()
            upload_url = data["uri"]
            creation_id = data["id"]

            # Step 2: upload bytes
            with open(path, "rb") as f:
                video_data = f.read()

            r2 = await client.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(size),
                },
                content=video_data,
            )
            r2.raise_for_status()

            # Step 3: wait for processing (up to 2.5 min)
            for _ in range(30):
                await asyncio.sleep(5)
                r3 = await client.get(
                    f"{_GRAPH}/{creation_id}",
                    params={"fields": "status_code", "access_token": token},
                )
                status = r3.json().get("status_code")
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    raise RuntimeError("Instagram media processing failed.")

            # Step 4: publish
            r4 = await client.post(
                f"{_GRAPH}/{ig_user_id}/media_publish",
                params={"access_token": token},
                json={"creation_id": creation_id},
            )
            r4.raise_for_status()
            media_id = r4.json()["id"]

        return f"https://www.instagram.com/p/{media_id}/"
