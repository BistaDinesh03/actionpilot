import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.agent.loop import AgentLoop
from app.services.agent.models import AgentPlan, AgentRequest, PlanStep, ToolResult
from app.services.agent.registry import ToolRegistry
from app.services.execution.executor import BrowserExecutor, ExecutionStopped
from app.services.execution.run_state import RUN_STATUSES, InvalidTransition, validate_transition

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def demo_server():
    process = subprocess.Popen([sys.executable, "-m", "http.server", "4173", "--directory", str(ROOT / "demo-site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    yield "http://127.0.0.1:4173"
    process.terminate()
    process.wait(timeout=5)


def wait_for(predicate, timeout=15, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def wait_status(client, run_id, wanted, timeout=25):
    if isinstance(wanted, str):
        wanted = {wanted}
    deadline = time.time() + timeout
    state = client.get(f"/api/runs/{run_id}").json()
    while time.time() < deadline:
        state = client.get(f"/api/runs/{run_id}").json()
        if state["status"] in wanted:
            return state
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} never reached {sorted(wanted)}; last status={state['status']} error={state.get('error')}")


def pending_plan(action="send", risk="high"):
    return AgentPlan(request="Send the update", intent="test", confidence=1.0, steps=[PlanStep(tool="fake", action=action, risk=risk)])


# --- run state machine -----------------------------------------------------


def test_valid_transitions_are_accepted():
    validate_transition("queued", "running")
    validate_transition("queued", "stopped")
    validate_transition("running", "paused")
    validate_transition("running", "waiting_confirmation")
    validate_transition("paused", "running")
    validate_transition("waiting_confirmation", "running")
    validate_transition("waiting_confirmation", "stopped")
    validate_transition("completed", "completed")  # same-status writes are no-ops


def test_invalid_transitions_raise():
    with pytest.raises(InvalidTransition):
        validate_transition("completed", "running")
    with pytest.raises(InvalidTransition):
        validate_transition("stopped", "queued")
    with pytest.raises(InvalidTransition):
        validate_transition("failed", "paused")
    with pytest.raises(InvalidTransition):
        validate_transition("running", "queued")
    with pytest.raises(InvalidTransition):
        validate_transition("running", "expired")
    assert set(RUN_STATUSES) == {"queued", "running", "waiting_confirmation", "paused", "completed", "failed", "stopped"}


def test_set_run_enforces_the_state_machine(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "paused")
    main.set_run(run_id, "running")
    with pytest.raises(InvalidTransition):
        main.set_run(run_id, "queued")
    main.set_run(run_id, "completed", current_action="Complete")
    with pytest.raises(InvalidTransition):
        main.set_run(run_id, "running")
    main.set_run(run_id, "completed")  # idempotent rewrite of the same status


def test_control_endpoints_are_idempotent_on_terminal_runs(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "completed", current_action="Complete")
    assert client.post(f"/api/runs/{run_id}/pause").json()["status"] == "completed"
    assert client.post(f"/api/runs/{run_id}/resume").json()["status"] == "completed"
    assert client.post(f"/api/runs/{run_id}/stop").json()["status"] == "completed"
    assert client.post(f"/api/agent/runs/{run_id}/pause").json()["status"] == "completed"
    assert client.post(f"/api/agent/runs/{run_id}/resume").json()["status"] == "completed"
    assert client.post(f"/api/agent/runs/{run_id}/stop").json()["status"] == "completed"


# --- approvals -------------------------------------------------------------


def test_approval_lifecycle_lists_approves_and_conflicts(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "waiting_confirmation")
    approval_id = main.create_approval(run_id, 0, "Send email", {"action": "send", "risk": "high"})

    pending = client.get("/api/approvals", params={"status": "pending"}).json()
    assert [item["id"] for item in pending] == [approval_id]
    scoped = client.get("/api/approvals", params={"run_id": run_id}).json()
    assert len(scoped) == 1
    assert scoped[0]["summary"] == "Send email"
    assert scoped[0]["detail"] == {"action": "send", "risk": "high"}
    assert scoped[0]["status"] == "pending"

    approved = client.post(f"/api/approvals/{approval_id}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved"
    assert body["resolved_at"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
    assert client.post(f"/api/approvals/{approval_id}/approve").status_code == 409
    assert client.post("/api/approvals/not-a-real-id/reject").status_code == 404
    assert client.get("/api/approvals", params={"status": "weird"}).status_code == 400


def test_rejecting_approval_stops_the_waiting_run(client):
    run_id = main.create_pending_agent_run(pending_plan())
    main.set_run(run_id, "running")
    main.set_run(run_id, "waiting_confirmation")
    approval_id = main.create_approval(run_id, 0, "Delete record", {"action": "delete"})

    rejected = client.post(f"/api/approvals/{approval_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "stopped"
    assert client.post(f"/api/approvals/{approval_id}/reject").status_code == 409


# --- activity feed ---------------------------------------------------------


def test_activity_feed_records_foundation_events(client):
    client.post("/api/skills", json={"name": "Activity Probe", "steps": []})
    client.post("/api/memory", json={"type": "user_preference", "title": "Format", "value": "Short posts"})

    events = client.get("/api/activity").json()
    names = [event["event"] for event in events]
    assert "skill_created" in names
    assert "memory_created" in names
    assert names.index("memory_created") < names.index("skill_created")

    limited = client.get("/api/activity", params={"limit": 1}).json()
    assert len(limited) == 1
    assert set(limited[0]) == {"id", "event", "detail", "created_at"}

    client.delete(f"/api/memory/{client.get('/api/memory').json()[0]['id']}")
    names = [event["event"] for event in client.get("/api/activity").json()]
    assert "memory_deleted" in names


# --- agent loop gate + progress -------------------------------------------


class _FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


class _FakeTool:
    name = "fake"
    description = "test"
    capabilities = []
    risk_level = "low"

    def can_handle(self, request):
        return True

    def plan(self, request):
        return self.steps

    def execute(self, plan, approved=False):
        return ToolResult(status="completed", output={"action": plan.action, "approved": approved})


def loop_with(steps, max_steps=15):
    registry = ToolRegistry()
    registry.register(_FakeTool())
    return AgentLoop(_FakeAgent(steps), registry, max_steps=max_steps)


def test_loop_without_gate_preserves_waiting_confirmation():
    state = loop_with([PlanStep(tool="fake", action="send", risk="high")]).run("send", [])
    assert state.status == "waiting_confirmation"
    assert len(state.observations) == 2  # planning_next_step + approval_required


def test_loop_gate_approval_runs_the_high_risk_step():
    seen = {}

    def gate(index, step):
        seen["index"] = index
        seen["action"] = step.get("action")
        return None

    state = loop_with([PlanStep(tool="fake", action="send", risk="high")]).run("send", [], gate=gate)
    assert state.status == "completed"
    assert seen == {"index": 0, "action": "send"}
    assert state.tool_history[0]["status"] == "completed"


def test_loop_gate_rejection_stops_the_run():
    state = loop_with([PlanStep(tool="fake", action="send", risk="high")]).run("send", [], gate=lambda _i, _s: "Approval rejected")
    assert state.status == "stopped"
    assert state.error == "Approval rejected"
    assert state.tool_history == []


def test_loop_progress_reports_the_step_lifecycle():
    events = []
    steps = [PlanStep(tool="fake", action="one"), PlanStep(tool="fake", action="two")]
    state = loop_with(steps).run("cycle", [], progress=lambda event, index, _data: events.append((event, index)))
    assert state.status == "completed"
    assert events == [("step_started", 0), ("step_completed", 0), ("step_started", 1), ("step_completed", 1)]


# --- executor gate ---------------------------------------------------------


def test_executor_gate_reject_stops_before_the_high_risk_step(tmp_path):
    executor = BrowserExecutor(tmp_path)
    step = {"type": "click", "label": "Final purchase", "risk_level": "high", "target": {"role": "button", "name": "Buy"}}
    with pytest.raises(ExecutionStopped, match="Approval rejected"):
        executor.execute([step], gate=lambda _index, _step: "Approval rejected")


# --- threaded agent run ----------------------------------------------------


def test_agent_run_is_threaded_with_real_pause_resume_stop(client, monkeypatch):
    def fake_run(request, skills, variables=None, stop_event=None, pause_event=None, gate=None, progress=None):
        from app.services.agent.state import AgentState

        state = AgentState(task_id="fake", goal=request, status="running")
        if progress:
            progress("step_started", 0, {"step": {"label": "Investigate", "type": "agent"}})
        active = 0.0
        while active < 5.0:
            if stop_event is not None and stop_event.is_set():
                state.status = "stopped"
                return state
            if pause_event is None or not pause_event.is_set():
                active += 0.1
            time.sleep(0.1)
        if progress:
            progress("step_completed", 0, {"status": "completed"})
        state.current_step = 1
        state.result = {"answer": "done"}
        return state

    monkeypatch.setattr(main.agent_loop, "run", fake_run)

    created = client.post("/api/agent/run", json={"request": "Research recent AI automation posts"}).json()
    assert created["status"] == "queued"
    run_id = created["run_id"]
    assert created["state"]["plan"]["intent"] == "web_research"

    wait_status(client, run_id, "running")
    detail = client.get(f"/api/agent/runs/{run_id}").json()
    assert detail["steps"], detail
    assert detail["steps"][0]["label"] == "Investigate"
    assert detail["steps"][0]["action_type"] == "agent"

    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    time.sleep(0.3)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "paused"

    resumed = client.post(f"/api/agent/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"

    stopped = client.post(f"/api/agent/runs/{run_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    wait_for(lambda: run_id not in main.run_controls, timeout=10)
    events = [event["event"] for event in client.get("/api/activity").json()]
    for expected in ("agent_planned", "agent_run_started", "run_paused", "run_resumed", "run_stopped", "agent_run_finished"):
        assert expected in events, expected


# --- end-to-end approval flow against the local demo site ------------------


def high_risk_steps(base_url):
    # "Open product" is visible on a fresh page load; "Add to cart" only exists
    # after opening a product, so the gated click must target the product card.
    return [
        {"type": "navigate", "label": "Open Demo Shop", "url": base_url},
        {"type": "type", "label": "Search keyboard", "target": {"role": "textbox", "placeholder": "Search products"}, "value": "keyboard"},
        {"type": "click", "label": "Open keyboard product", "risk_level": "high", "target": {"role": "button", "name": "Open product"}},
    ]


def test_high_risk_run_waits_for_approval_then_completes(client, demo_server):
    skill = client.post("/api/skills", json={"name": "Foundation Gate Pass", "steps": high_risk_steps(demo_server)}).json()
    run = client.post("/api/runs", json={"skill_id": skill["id"]}).json()
    wait_status(client, run["id"], "waiting_confirmation", timeout=30)

    pending = client.get("/api/approvals", params={"status": "pending", "run_id": run["id"]}).json()
    assert len(pending) == 1
    assert pending[0]["summary"] == "Open keyboard product"

    approved = client.post(f"/api/approvals/{pending[0]['id']}/approve")
    assert approved.status_code == 200
    final = wait_status(client, run["id"], "completed", timeout=30)
    assert all(step["status"] == "completed" for step in final["steps"])
    wait_for(lambda: run["id"] not in main.run_controls, timeout=10)


def test_high_risk_run_rejection_stops_the_run(client, demo_server):
    skill = client.post("/api/skills", json={"name": "Foundation Gate Reject", "steps": high_risk_steps(demo_server)}).json()
    run = client.post("/api/runs", json={"skill_id": skill["id"]}).json()
    wait_status(client, run["id"], "waiting_confirmation", timeout=30)

    pending = client.get("/api/approvals", params={"status": "pending", "run_id": run["id"]}).json()
    assert len(pending) == 1
    rejected = client.post(f"/api/approvals/{pending[0]['id']}/reject")
    assert rejected.status_code == 200

    final = wait_status(client, run["id"], "stopped", timeout=30)
    assert final["status"] == "stopped"
    wait_for(lambda: run["id"] not in main.run_controls, timeout=10)
