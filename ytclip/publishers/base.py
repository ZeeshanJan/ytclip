from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Publisher(ABC):
    name: str
    display_name: str
    icon: str
    color: str

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @abstractmethod
    def auth_url(self, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str) -> dict: ...
    # Returns: {access_token, refresh_token, expires_at, user_handle, user_avatar, extra}

    @abstractmethod
    async def refresh(self, connection: dict) -> dict: ...

    @abstractmethod
    async def upload(
        self,
        connection: dict,
        path: Path,
        title: str,
        description: str = "",
        privacy: str = "public",
        **kwargs: Any,
    ) -> str: ...
    # Returns the platform URL of the published post

    async def _maybe_refresh(self, connection: dict) -> dict:
        from datetime import datetime, timezone
        expires_at = connection.get("expires_at")
        if not expires_at:
            return connection
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if (exp - datetime.now(timezone.utc)).total_seconds() < 300:
            return await self.refresh(connection)
        return connection
