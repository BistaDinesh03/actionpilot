from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from googleapiclient.discovery import Resource, build

from .models import EmailAddress, EmailDraft, MessageMetadata


class GmailClient:
    def __init__(self, credentials: Any, api: Resource | None = None) -> None:
        self.api = api or build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def profile(self) -> dict[str, Any]:
        return self.api.users().getProfile(userId="me").execute()

    def search(self, query: str, limit: int = 10) -> list[MessageMetadata]:
        response = self.api.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        return [self.metadata(item["id"]) for item in response.get("messages", [])]

    def metadata(self, message_id: str) -> MessageMetadata:
        message = self.api.users().messages().get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
        headers = {header["name"].lower(): header["value"] for header in message.get("payload", {}).get("headers", [])}
        return MessageMetadata(id=message["id"], thread_id=message.get("threadId"), sender=headers.get("from"), subject=headers.get("subject"), snippet=message.get("snippet"), date=headers.get("date"))

    def create_draft(self, draft: EmailDraft, sender: str | None = None) -> dict[str, Any]:
        raw = self._raw_message(draft, sender)
        return self.api.users().drafts().create(userId="me", body={"message": {"raw": raw, **({"threadId": draft.thread_id} if draft.thread_id else {})}}).execute()

    def send(self, draft: EmailDraft, sender: str | None = None) -> dict[str, Any]:
        raw = self._raw_message(draft, sender)
        body: dict[str, Any] = {"raw": raw}
        if draft.thread_id:
            body["threadId"] = draft.thread_id
        return self.api.users().messages().send(userId="me", body=body).execute()

    @staticmethod
    def _raw_message(draft: EmailDraft, sender: str | None) -> str:
        message = EmailMessage()
        message["To"] = f"{draft.to.name} <{draft.to.email}>" if draft.to.name else str(draft.to.email)
        if sender:
            message["From"] = sender
        message["Subject"] = draft.subject
        message.set_content(draft.body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
