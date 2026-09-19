import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.gmail.auth import GmailAuth, SCOPES
from app.services.gmail.models import EmailAddress, MessageMetadata


class FakeGmailClient:
    def __init__(self, contacts=None):
        self.sent = []
        self.drafts = []
        self.contacts = contacts or [EmailAddress(name="John Smith", email="john@example.com")]

    def profile(self):
        return {"emailAddress": "me@example.com"}

    def search(self, query, limit=10):
        if "from:" in query or "to:" in query:
            return [MessageMetadata(id="message-1", thread_id="thread-1", sender='John Smith <john@example.com>', subject="Meeting", snippet="Hello", date="today")]
        return []

    def create_draft(self, draft):
        self.drafts.append(draft)
        return {"id": "draft-1"}

    def send(self, draft):
        self.sent.append(draft)
        return {"id": "sent-1"}


@pytest.fixture
def gmail_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    fake = FakeGmailClient()
    main.gmail_service.auth = GmailAuth(tmp_path / "token.json", client_id="client", client_secret="secret", redirect_uri="http://localhost:8000/api/gmail/callback")
    main.gmail_service.set_mock_client(fake)
    with TestClient(main.app) as test_client:
        yield test_client, fake
    main.gmail_service.set_mock_client(None)


def test_oauth_url_creation(monkeypatch, tmp_path):
    auth = GmailAuth(tmp_path / "token.json", client_id="client", client_secret="secret", redirect_uri="http://localhost/callback")

    class FakeFlow:
        def __init__(self):
            self.redirect_uri = None

        def authorization_url(self, **kwargs):
            return "https://accounts.google.com/o/oauth2/auth?state=test", "test"

    monkeypatch.setattr("app.services.gmail.auth.Flow.from_client_config", lambda *args, **kwargs: FakeFlow())
    assert auth.authorization_url().startswith("https://accounts.google.com/")


def test_disconnected_state(tmp_path):
    service = main.GmailService(tmp_path)
    assert service.status() == "not_connected"


def test_token_refresh_logic(monkeypatch, tmp_path):
    from google.oauth2.credentials import Credentials

    auth = GmailAuth(tmp_path / "token.json", client_id="client", client_secret="secret", redirect_uri="http://localhost/callback")
    credentials = Credentials(token="old-token", refresh_token="refresh-token", token_uri="https://oauth2.googleapis.com/token", client_id="client", client_secret="secret", scopes=SCOPES)
    credentials.expiry = datetime.now(timezone.utc) - timedelta(minutes=5)
    auth.save(credentials)

    def refresh(self, _request):
        self.token = "refreshed-token"
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    loaded = auth.load()
    assert loaded is not None
    assert loaded.token == "refreshed-token"


def test_email_command_resolves_contact_and_creates_draft(gmail_client):
    client, fake = gmail_client
    response = client.post("/api/command", json={"command": "Email John and tell him I'll arrive at 3 PM."})
    body = response.json()
    assert body["intent"] == "send_email"
    assert body["recipient"]["email"] == "john@example.com"
    assert body["body"] == "I'll arrive at 3 PM"
    assert body["requires_confirmation"] is True
    assert body["draft_id"] == "draft-1"
    assert len(fake.drafts) == 1


def test_send_refuses_without_approval_and_sends_once_with_approval(gmail_client):
    client, fake = gmail_client
    payload = {"to": {"name": "John Smith", "email": "john@example.com"}, "subject": "Arrival", "body": "I will arrive at 3 PM"}
    refused = client.post("/api/gmail/send", json=payload)
    assert refused.status_code == 400
    assert fake.sent == []
    sent = client.post("/api/gmail/send", json={**payload, "approved": True})
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert len(fake.sent) == 1


def test_reply_flow_requires_message_selection_or_uses_single_message(gmail_client):
    client, fake = gmail_client
    response = client.post("/api/command", json={"command": "Reply to John's last email saying thanks"})
    body = response.json()
    assert body["intent"] == "reply_email"
    assert body["message_id"] == "message-1"
    assert body["subject"] == "Re: Meeting"


def test_ambiguous_recipient_does_not_create_draft(gmail_client):
    client, fake = gmail_client
    fake.search = lambda query, limit=10: [
        MessageMetadata(id="one", sender="John Smith <john@example.com>"),
        MessageMetadata(id="two", sender="John Lee <john2@example.com>"),
    ]
    response = client.post("/api/command", json={"command": "Email John and tell him hello"})
    body = response.json()
    assert body["candidates"]
    assert body["message"] == "Choose a recipient before preparing the email."
    assert fake.drafts == []


def test_connections_never_expose_tokens(gmail_client):
    client, _ = gmail_client
    response = client.get("/api/connections")
    assert response.json() == {"gmail": {"status": "connected"}}
    assert "token" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_malformed_email_is_rejected(gmail_client):
    client, _ = gmail_client
    response = client.post("/api/gmail/send", json={"to": {"name": "", "email": "not-an-email"}, "body": "hello", "approved": True})
    assert response.status_code == 422
