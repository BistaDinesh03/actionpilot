from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class EmailAddress(BaseModel):
    name: str = ""
    email: EmailStr


class MessageMetadata(BaseModel):
    id: str
    thread_id: str | None = None
    sender: str | None = None
    subject: str | None = None
    snippet: str | None = None
    date: str | None = None


class EmailIntent(BaseModel):
    intent: str = Field(pattern=r"^(send_email|reply_email|clarify)$")
    recipient_query: str | None = None
    recipient: EmailAddress | None = None
    subject: str | None = None
    body: str | None = None
    message_id: str | None = None
    requires_confirmation: bool = True
    candidates: list[EmailAddress] = Field(default_factory=list)
    message_candidates: list[MessageMetadata] = Field(default_factory=list)
    connected: bool = False
    message: str | None = None


class EmailDraft(BaseModel):
    to: EmailAddress
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = None
    message_id: str | None = None


class EmailSendRequest(EmailDraft):
    approved: bool = False


