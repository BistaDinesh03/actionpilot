"""Upfront approval gate: waiting runs carry one discoverable approval row,
an APPROVAL REQUESTED audit event, a correct current step, and approving or
rejecting continues or stops the run through the existing executors."""

import threading
import time

from fastapi.testclient import TestClient

from app import main

DESKTOP_REQUEST = "Open notepad and delete the requested file"


def plan_for(client, request=DESKTOP_REQUEST):
    response = client.post("/api/agent/plan", json={"request": request})
    assert response.status_code == 200
    return response.json()


def approvals_for(client, run_id):
    return client.get("/api/approvals", params={"run_id": run_id}).json()


def pending_for(client, run_id):
    rows = [row for row in approvals_for(client, run_id) if row["status"] == "pending"]
    return rows[0] if rows else None


def wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def test_upfront_gate_creates_one_approval_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "upfront.db")
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as client:
        plan = plan_for(client)
        assert plan["intent"] == "desktop"
        assert plan["requires_confirmation"] is True
        high_index = next(index for index, step in enumerate(plan["steps"]) if step["risk"] == "high")

        result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        assert result["status"] == "waiting_confirmation"
        run_id = result["run_id"]

        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "waiting_confirmation"
        # current_step points at the approval step; the timeline covers the real step count.
        assert len(run["steps"]) == len(plan["steps"])
        assert run["current_step"] == high_index
        assert run["current_step"] < len(run["steps"])

        pending = client.get("/api/approvals", params={"run_id": run_id, "status": "pending"}).json()
        assert len(pending) == 1
        approval = pending[0]
        assert approval["kind"] == "upfront"
        assert approval["step_index"] == high_index
        assert approval["summary"] == plan["steps"][high_index]["action"]

        events = client.get("/api/activity", params={"limit": 50}).json()
        assert any(event["event"] == "approval_requested" for event in events)

        # A second gated plan is a separate run, each run keeps exactly one approval row.
        second = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        assert second["run_id"] != run_id
        assert len(approvals_for(client, run_id)) == 1
        assert len(approvals_for(client, second["run_id"])) == 1


def test_upfront_approval_approve_resumes_the_same_run(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "upfront-approve.db")
    main.run_controls.clear()
    main.init_db()
    spawned = []
    monkeypatch.setattr(main, "execute_agent_run", lambda run_id, request, variables: spawned.append((run_id, request, variables)))
    with TestClient(main.app) as client:
        plan = plan_for(client)
        result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        run_id = result["run_id"]
        approval = pending_for(client, run_id)
        assert approval is not None

        resolved = client.post(f"/api/approvals/{approval['id']}/approve")
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "approved"
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
        assert spawned == [(run_id, DESKTOP_REQUEST, plan["variables"])]
        # No duplicate approval rows, and the decision cannot be replayed.
        assert len(approvals_for(client, run_id)) == 1
        assert client.post(f"/api/approvals/{approval['id']}/approve").status_code == 409


def test_upfront_approval_reject_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "upfront-reject.db")
    main.run_controls.clear()
    main.init_db()
    spawned = []
    monkeypatch.setattr(main, "execute_agent_run", lambda run_id, request, variables: spawned.append((run_id, request, variables)))
    with TestClient(main.app) as client:
        plan = plan_for(client)
        result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        run_id = result["run_id"]
        approval = pending_for(client, run_id)
        assert approval is not None

        resolved = client.post(f"/api/approvals/{approval['id']}/reject")
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "rejected"
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "stopped"
        assert spawned == []
        rows = approvals_for(client, run_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "rejected"


def test_gate_reuses_upfront_approval_and_mid_run_gate_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "upfront-gate.db")
    main.run_controls.clear()
    main.init_db()
    spawned = []
    monkeypatch.setattr(main, "execute_agent_run", lambda run_id, request, variables: spawned.append((run_id, request, variables)))
    with TestClient(main.app) as client:
        plan = plan_for(client)
        result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        run_id = result["run_id"]
        approval = pending_for(client, run_id)
        high_index = approval["step_index"]
        client.post(f"/api/approvals/{approval['id']}/approve")

        controls = {"stop": threading.Event(), "pause": threading.Event()}
        gate = main.approval_gate(run_id, controls)
        # The approved upfront step proceeds without asking (or row) again.
        assert gate(high_index, {"label": plan["steps"][high_index]["action"], "risk": "high"}) is None
        assert len(approvals_for(client, run_id)) == 1

        # A different step still goes through the existing mid-run gate: fresh row, approve resumes it.
        other_index = 0 if high_index != 0 else 1
        outcome = {}

        def call_gate():
            outcome["reason"] = gate(other_index, {"label": "Open notepad", "risk": "high"})

        worker = threading.Thread(target=call_gate, daemon=True)
        worker.start()
        wait_until(lambda: len(approvals_for(client, run_id)) == 2)
        pending = [row for row in approvals_for(client, run_id) if row["status"] == "pending"]
        assert len(pending) == 1
        assert pending[0]["step_index"] == other_index
        assert client.post(f"/api/approvals/{pending[0]['id']}/approve").status_code == 200
        worker.join(timeout=5)
        assert outcome.get("reason") is None
        rows = approvals_for(client, run_id)
        assert len(rows) == 2
        assert {row["status"] for row in rows} == {"approved"}
        # Mid-run approvals must not trigger a second run resume.
        assert len(spawned) == 1


def test_run_skill_upfront_approval_resumes_via_run_executor(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "upfront-skill.db")
    main.run_controls.clear()
    main.init_db()
    spawned = []
    monkeypatch.setattr(main, "execute_run", lambda *args: spawned.append(args))
    with TestClient(main.app) as client:
        skill = client.post(
            "/api/skills",
            json={
                "name": "Demo Keyboard Search",
                "steps": [{"type": "click", "label": "Open product", "risk_level": "high", "target": {"role": "button", "name": "Open product"}}],
            },
        )
        assert skill.status_code == 201
        plan = plan_for(client, "Run my keyboard workflow")
        assert plan["intent"] == "run_skill"
        assert plan["requires_confirmation"] is True

        result = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
        assert result["status"] == "waiting_confirmation"
        run_id = result["run_id"]
        approval = pending_for(client, run_id)
        assert approval is not None
        assert approval["step_index"] == 0

        resolved = client.post(f"/api/approvals/{approval['id']}/approve")
        assert resolved.status_code == 200
        assert spawned == [(run_id, plan["steps"][0]["parameters"]["skill_id"], plan["variables"])]
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
        assert len(approvals_for(client, run_id)) == 1
