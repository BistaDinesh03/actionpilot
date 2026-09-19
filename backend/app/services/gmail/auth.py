from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailAuth:
    def __init__(self, token_path: Path, client_id: str | None = None, client_secret: str | None = None, redirect_uri: str | None = None) -> None:
        self.token_path = token_path
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/gmail/callback")
        self._states: set[str] = set()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def _client_config(self) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Gmail OAuth is not configured")
        return {"web": {"client_id": self.client_id, "client_secret": self.client_secret, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [self.redirect_uri]}}

    def flow(self, state: str | None = None) -> Flow:
        flow = Flow.from_client_config(self._client_config(), scopes=SCOPES, state=state)
        flow.redirect_uri = self.redirect_uri
        return flow

    def authorization_url(self) -> str:
        state = secrets.token_urlsafe(32)
        self._states.add(state)
        url, _ = self.flow(state).authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
        return url

    def exchange_code(self, code: str, state: str | None) -> Credentials:
        if not state or state not in self._states:
            raise ValueError("Invalid or expired Gmail OAuth state")
        self._states.remove(state)
        flow = self.flow(state)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        self.save(credentials)
        return credentials

    def load(self) -> Credentials | None:
        if not self.token_path.is_file():
            return None
        try:
            credentials = Credentials.from_authorized_user_info(json.loads(self.token_path.read_text(encoding="utf-8")), SCOPES)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.save(credentials)
            return credentials if credentials.valid else None
        except Exception:
            return None

    def save(self, credentials: Credentials) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        try:
            self.token_path.chmod(0o600)
        except OSError:
            pass

    def disconnect(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()
