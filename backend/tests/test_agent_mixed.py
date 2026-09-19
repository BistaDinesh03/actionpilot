from fastapi.testclient import TestClient

from app import main
from app.services.agent.models import ToolResult
from app.services.gmail.models import EmailAddress, MessageMetadata


class MixedGmail:
    def __init__(self):
        self.drafts = []
        self.sent = []

    def search(self, query, limit=10):
        return [MessageMetadata(id="message-1", sender="John Smith <john@example.com>", subject="AI", snippet="post")]

    def create_draft(self, draft):
        self.drafts.append(draft)
        return {"id": "draft-summary"}

    def send(self, draft):
        self.sent.append(draft)
        return {"id": "sent"}


def test_mixed_research_creates_draft_but_does_not_send(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "mixed.db")
    main.init_db()
    gmail = MixedGmail()
    main.gmail_service.set_mock_client(gmail)
    monkeypatch.setattr(main.agent_registry.get("web_research"), "execute", lambda plan, approved=False: ToolResult(status="completed", output={"sources": [{"title": "AI post", "url": "https://example.com", "excerpt": "automation"}], "ideas": ["Idea one"]}))
    try:
        with TestClient(main.app) as client:
            plan = client.post("/api/agent/plan", json={"request": "Research AI automation and email John the summary"}).json()
            result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        assert result["status"] == "waiting_confirmation"
        assert result["requires_confirmation"] is True
        assert result["output"]["draft_id"] == "draft-summary"
        assert len(gmail.drafts) == 1
        assert gmail.sent == []
    finally:
        main.gmail_service.set_mock_client(None)
