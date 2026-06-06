from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .base import Publisher

_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_ME_URL = "https://api.linkedin.com/v2/me"
_ASSETS_URL = "https://api.linkedin.com/v2/assets"
_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


class LinkedInPublisher(Publisher):
    name = "linkedin"
    display_name = "LinkedIn"
    icon = "fa-brands fa-linkedin"
    color = "#0077b5"

    def auth_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "w_member_social r_liteprofile",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            tokens = r.json()
            token = tokens["access_token"]

            r2 = await client.get(
                f"{_ME_URL}?projection=(id,localizedFirstName,localizedLastName)",
                headers={"Authorization": f"Bearer {token}"},
            )
            profile = r2.json()
            member_id = f"urn:li:person:{profile['id']}"
            name = f"{profile.get('localizedFirstName', '')} {profile.get('localizedLastName', '')}".strip()

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 5184000))
        ).isoformat()

        return {
            "access_token": token,
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": expires_at,
            "user_handle": name,
            "user_avatar": "",
            "extra": {"member_id": member_id},
        }

    async def refresh(self, connection: dict) -> dict:
        # LinkedIn 60-day tokens have no refresh endpoint in standard tier
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
        member_id = (connection.get("extra") or {}).get("member_id", "")
        if not member_id:
            raise ValueError("LinkedIn member ID not found — please reconnect.")

        async with httpx.AsyncClient(timeout=600) as client:
            # Step 1: register upload
            r = await client.post(
                f"{_ASSETS_URL}?action=registerUpload",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                        "owner": member_id,
                        "serviceRelationships": [{
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent",
                        }],
                    }
                },
            )
            r.raise_for_status()
            val = r.json()["value"]
            asset_urn = val["asset"]
            upload_url = val["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]

            # Step 2: upload binary
            with open(path, "rb") as f:
                video_data = f.read()
            await client.put(upload_url, content=video_data, headers={"Authorization": f"Bearer {token}"})

            # Step 3: create post
            visibility = "PUBLIC" if privacy == "public" else "CONNECTIONS"
            r3 = await client.post(
                _POSTS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                json={
                    "author": member_id,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": f"{title}\n\n{description}".strip()},
                            "shareMediaCategory": "VIDEO",
                            "media": [{
                                "status": "READY",
                                "description": {"text": description or title},
                                "media": asset_urn,
                                "title": {"text": title[:200]},
                            }],
                        }
                    },
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
                },
            )
            r3.raise_for_status()
            post_urn = r3.headers.get("x-restli-id", "")

        return f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else "https://www.linkedin.com/"
