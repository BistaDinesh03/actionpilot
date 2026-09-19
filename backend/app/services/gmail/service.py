from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .auth import GmailAuth
from .client import GmailClient
from .models import EmailAddress, EmailDraft, EmailIntent, EmailSendRequest, MessageMetadata


class GmailService:
    def __init__(self, root: Path, client_factory: Callable[[Any], GmailClient] | None = None) -> None:
        self.auth = GmailAuth(root / "runtime" / "gmail" / "token.json")
        self.client_factory = client_factory or (lambda credentials: GmailClient(credentials))
        self._client_override: GmailClient | None = None

    def status(self) -> str:
        return "connected" if self.auth.load() or self._client_override else "not_connected"

    def client(self) -> GmailClient:
        if self._client_override:
            return self._client_override
        credentials = self.auth.load()
        if not credentials:
            raise RuntimeError("Gmail is not connected")
        return self.client_factory(credentials)

    def set_mock_client(self, client: GmailClient | None) -> None:
        self._client_override = client

    def connect_url(self) -> str:
        return self.auth.authorization_url()

    def complete_connection(self, code: str, state: str | None) -> None:
        self.auth.exchange_code(code, state)

    def disconnect(self) -> None:
        self._client_override = None
        self.auth.disconnect()

    def profile(self) -> dict[str, Any]:
        return self.client().profile()

    def find_contacts(self, query: str) -> list[EmailAddress]:
        messages = self.client().search(f"from:({query}) OR to:({query})", limit=10)
        contacts: dict[str, EmailAddress] = {}
        for message in messages:
            if message.sender:
                match = re.search(r"(?P<name>.*?)\s*<(?P<email>[^>]+)>", message.sender)
                if match:
                    contact = EmailAddress(name=match.group("name").strip(' "'), email=match.group("email"))
                    contacts[str(contact.email).lower()] = contact
        return list(contacts.values())

    def recent_messages(self, query: str) -> list[MessageMetadata]:
        return self.client().search(query, limit=10)

    def create_draft(self, draft: EmailDraft) -> dict[str, Any]:
        return self.client().create_draft(draft)

    def send(self, request: EmailSendRequest) -> dict[str, Any]:
        if not request.approved:
            raise PermissionError("Explicit approval is required before sending email")
        return self.client().send(request)


def parse_email_command(command: str) -> EmailIntent | None:
    text = command.strip()
    lowered = text.lower()
    is_reply = lowered.startswith("reply") or "reply to" in lowered
    if not (is_reply or re.search(r"\b(email|send an email|send)\b", lowered)):
        return None
    summary_match = re.search(r"(?:email|to)\s+(?P<recipient>[A-Za-z][A-Za-z .'-]*?)\s+the summary\.?$", text, re.IGNORECASE)
    if summary_match:
        return EmailIntent(intent="send_email", recipient_query=summary_match.group("recipient").strip(" .,"), body="the summary", requires_confirmation=True)
    recipient_match = re.search(r"(?:to|email|reply to)\s+(?P<recipient>[A-Za-z][A-Za-z .'-]*?)(?:\s+(?:and tell|saying|that|to say|the summary)\s+|\s*$)", text, re.IGNORECASE)
    body_match = re.search(r"(?:and tell(?: him| her)?|saying|that|to say|the summary)\s+(?P<body>.+)$", text, re.IGNORECASE)
    recipient = recipient_match.group("recipient").strip(" .,") if recipient_match else None
    body = body_match.group("body").strip().rstrip(".") if body_match else None
    if not recipient or not body:
        return EmailIntent(intent="clarify", requires_confirmation=True, message="Tell me who to contact and what to say.")
    return EmailIntent(intent="reply_email" if is_reply else "send_email", recipient_query=recipient, body=body, requires_confirmation=True)
