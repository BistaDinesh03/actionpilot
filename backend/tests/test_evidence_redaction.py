"""Approval and audit records are evidence, never a store for typed secrets.

Regression tests for the Phase-2 audit finding: approval detail used to keep
the full substituted step (including the typed ``value``) and audit rows kept
raw command text, so secrets typed into the command box would persist in the
local SQLite database. Both surfaces now mask secrets while keeping the
evidence of intent readable.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.agent.models import AgentPlan, PlanStep


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def pending_plan() -> AgentPlan:
    return AgentPlan(
        request="Create a local demo account",
        intent="local_account",
        confidence=1.0,
        steps=[PlanStep(tool="browser", action="Fill the account form", risk="low")],
    )


def audit_details(event: str) -> list[str]:
    with main.db() as connection:
        rows = connection.execute(
            "SELECT detail FROM audit_logs WHERE event = ? ORDER BY created_at", (event,)
        ).fetchall()
    return [row["detail"] for row in rows]


# --- audit text redaction ---------------------------------------------------


def test_redact_audit_text_masks_secret_assignments():
    text = "login as user=dines password=Hunter2 token: abc123 api_key=sk-live-5678 Authorization: Bearer eyJhbGciOi"
    masked = main.redact_audit_text(text)
    for secret in ("Hunter2", "abc123", "sk-live-5678", "eyJhbGciOi"):
        assert secret not in masked
    assert masked.count("[redacted]") >= 4
    assert "user=dines" in masked  # ordinary evidence of intent stays readable


def test_redact_audit_text_leaves_plain_text_alone():
    assert main.redact_audit_text("step 2: open the demo") == "step 2: open the demo"


def test_write_audit_stores_redacted_detail(client):
    main.write_audit("command_requested", "open the demo password=Hunter2")
    (detail,) = audit_details("command_requested")
    assert "Hunter2" not in detail
    assert "[redacted]" in detail
    assert "open the demo" in detail


def test_write_audit_keeps_the_500_char_bound(client):
    main.write_audit("run_created", "x" * 600)
    assert len(audit_details("run_created")[0]) == 500


def test_command_endpoint_never_stores_typed_secrets(client):
    response = client.post("/api/command", json={"command": "unmatched task password=Hunter2"})
    assert response.status_code == 200
    assert response.json()["matched"] is False
    (detail,) = audit_details("command_requested")
    assert "Hunter2" not in detail
    assert "[redacted]" in detail


# --- approval evidence ------------------------------------------------------


def test_approval_detail_never_stores_typed_values(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "waiting_confirmation")
    main.create_approval(
        run_id,
        0,
        "Type account email",
        {
            "action": "type",
            "value": "person@example.com",
            "target": {"label": "Email"},
            "parameters": {"session_id": "abc123", "value": "person@example.com"},
        },
    )
    stored = client.get("/api/approvals", params={"run_id": run_id}).json()[0]["detail"]
    assert stored["value"] == "[redacted]"
    assert stored["parameters"] == {"session_id": "abc123", "value": "[redacted]"}
    assert stored["target"] == {"label": "Email"}
    assert stored["action"] == "type"


def test_empty_typed_values_stay_untouched(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "waiting_confirmation")
    main.create_approval(run_id, 0, "Submit form", {"action": "click", "value": "", "parameters": {}})
    stored = client.get("/api/approvals", params={"run_id": run_id}).json()[0]["detail"]
    assert stored["value"] == ""
    assert stored["parameters"] == {}


def test_approving_a_redacted_detail_still_resumes_the_run(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "waiting_confirmation")
    approval_id = main.create_approval(
        run_id, 0, "Type account email", {"action": "type", "value": "person@example.com"}
    )
    approved = client.post(f"/api/approvals/{approval_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
