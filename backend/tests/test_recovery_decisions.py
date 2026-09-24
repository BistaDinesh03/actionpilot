"""Bounded recovery decisions (Milestone E).

A failed step is classified deterministically (never by an AI) into one of
five bounded outcomes — retry_after_delay, reobserve, replan, stop, or ask —
every decision is recorded as an audit event, delays are short and
interruptible by stop, verification failures stop immediately, and a human
is asked only when the failure genuinely needs a decision.
"""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from threading import Event, Timer

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.agent.loop import AgentLoop
from app.services.agent.models import AgentPlan, Decision, PlanStep, ToolResult, VerificationResult
from app.services.agent.recovery import RETRY_DELAY_SECONDS, RecoveryDecision, classify_recovery
from app.services.agent.registry import ToolRegistry
from app.services.agent.state import Observation

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def account_demo_url():
    """Serve demo-site on an ephemeral port so tests never touch :4173."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(ROOT / "demo-site")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/account.html"
    deadline = time.time() + 8
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base, timeout=1) as response:
                ready = response.status == 200
            if ready:
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError("hermetic demo server did not become ready")
    yield base
    process.terminate()
    process.wait(timeout=5)


def wait_status(client, run_id, wanted, timeout=60):
    deadline = time.time() + timeout
    state = client.get(f"/api/runs/{run_id}").json()
    while time.time() < deadline:
        state = client.get(f"/api/runs/{run_id}").json()
        if state["status"] == wanted:
            return state
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} never reached {wanted}; last status={state['status']} error={state.get('error')}")


# --- helpers -----------------------------------------------------------------


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


def step(risk="low", tool="browser", parameters=None, action="open page"):
    return PlanStep(tool=tool, action=action, risk=risk, parameters=parameters if parameters is not None else {"phase": "open"})


def failed(message, verification=None):
    output = {"verification": verification} if verification is not None else {}
    return ToolResult(status="failed", message=message, output=output)


def classify(result, *, attempt=0, budget=2, risk="low", can_reobserve=False, can_replan=False):
    return classify_recovery(step(risk=risk), result, attempt=attempt, budget=budget, can_reobserve=can_reobserve, can_replan=can_replan)


# --- classifier: stop ---------------------------------------------------------


def test_verification_failures_classify_as_stop():
    structured = classify(failed("Account creation could not be verified: success panel not visible", VerificationResult.from_checks({"result_visible": False}, summary="Not verified.").model_dump()))
    assert structured.kind == "stop"
    message_only = classify(failed("Account creation could not be verified: mismatch on name."))
    assert message_only.kind == "stop"
    for decision in (structured, message_only):
        assert decision.delay == 0.0
        assert decision.reason


def test_unsupported_and_target_failures_classify_as_stop():
    assert classify(failed("Delete file is not yet supported.")).kind == "stop"
    assert classify(failed("Target not found: no visible control matches the planned action.")).kind == "stop"
    assert classify(failed("Ambiguous target: 2 visible controls could match; refusing to guess.")).kind == "stop"
    assert classify(failed("Target not found: the only matching control has no stable selector.")).kind == "stop"


def test_high_risk_failures_always_stop():
    decision = classify(failed("transient read-only failure"), risk="high", budget=2)
    assert decision.kind == "stop"
    assert decision.delay == 0.0


def test_budget_exhaustion_stops_even_for_read_only_steps():
    assert classify(failed("transient read-only failure"), attempt=2, budget=2).kind == "stop"
    assert classify(failed("transient read-only failure"), attempt=0, budget=0).kind == "stop"


# --- classifier: ask and bounded retries --------------------------------------


def test_human_style_failures_classify_as_ask():
    decision = classify(failed("Permission denied by the local application."))
    assert decision.kind == "ask"
    assert decision.delay == 0.0
    assert decision.reason
    # Asking wins over an available retry budget — a human decides first.
    assert classify(failed("stored credential expired"), attempt=0, budget=2).kind == "ask"


def test_read_only_failures_retry_with_a_short_bounded_delay():
    first = classify(failed("transient read-only failure"), attempt=0, budget=2, can_reobserve=True, can_replan=True)
    assert first.kind == "retry_after_delay"
    assert first.delay == RETRY_DELAY_SECONDS == 0.25
    assert first.delay <= 5.0  # always short


def test_later_attempts_reobserve_or_replan_but_stay_bounded():
    reobserve = classify(failed("transient read-only failure"), attempt=1, budget=2, can_reobserve=True)
    assert reobserve.kind == "reobserve"
    replan = classify(failed("transient read-only failure"), attempt=1, budget=2, can_reobserve=True, can_replan=True)
    assert replan.kind == "replan"
    plain = classify(failed("transient read-only failure"), attempt=1, budget=2)
    assert plain.kind == "retry_after_delay"  # no seams available: plain bounded retry


def test_every_decision_is_a_valid_bounded_outcome():
    results = [
        classify(failed("boom"), attempt=attempt, budget=budget, can_reobserve=True, can_replan=True, risk=risk)
        for attempt, budget, risk in [(0, 2, "low"), (1, 2, "low"), (2, 2, "low"), (0, 0, "low"), (0, 2, "high"), (0, 9, "low")]
    ]
    for decision in results:
        assert decision.kind in {"retry_after_delay", "reobserve", "replan", "stop", "ask"}
        assert 0.0 <= decision.delay <= 5.0
        assert decision.reason
        # Round-trips as a structured model.
        RecoveryDecision.model_validate(decision.model_dump())


# --- loop: decisions are recorded and audited --------------------------------


class _BaseFailingTool:
    name = "browser"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self, failures, message="transient read-only failure", on_fail=None):
        self.failures = failures
        self.message = message
        self.on_fail = on_fail
        self.observe_calls = 0
        self.calls = []

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def observe(self, plan):
        self.observe_calls += 1
        return Observation(kind="browser", summary=f"observation {self.observe_calls}", data={"available": True, "elements": [], "elements_total": 0, "elements_truncated": False})

    def execute(self, plan, approved=False):
        self.calls.append(plan.action)
        if self.failures > 0:
            self.failures -= 1
            if self.on_fail is not None:
                self.on_fail()
            return ToolResult(status="failed", message=self.message)
        return ToolResult(status="completed", output={"action": plan.action})


class ObservingTool(_BaseFailingTool):
    """Has observe only: recovery can re-observe but not re-decide."""


class DecidingTool(_BaseFailingTool):
    """Has observe + adapt: recovery may take the bounded replan path."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.adapt_calls = 0

    def adapt(self, plan, observation):
        self.adapt_calls += 1
        return plan, Decision(kind="execute", reason="planned target still valid")


def loop_for(tool):
    registry = ToolRegistry()
    registry.register(tool)
    return AgentLoop(FakeAgent([step()]), registry)


def run_tool(tool, progress=None):
    return loop_for(tool).run("recover", [], progress=progress)


def recovery_events(events):
    return [data for event, _index, data in events if event == "recover"]


def recovery_decisions(state):
    return [item for item in state.observations if item.summary == "recovery_decision"]


def test_stop_decision_is_recorded_without_any_retry():
    tool = _BaseFailingTool(failures=99)  # mutating-style budget: submit phase below
    doomed = PlanStep(tool="browser", action="submit form", risk="low", parameters={"phase": "submit"})
    registry = ToolRegistry()
    registry.register(tool)
    events = []
    state = AgentLoop(FakeAgent([doomed]), registry).run("mutating", [], progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "failed"
    assert tool.calls == ["submit form"]  # stop: exactly one attempt
    decisions = recovery_decisions(state)
    assert len(decisions) == 1
    assert decisions[0].data["kind"] == "stop"
    audited = recovery_events(events)
    assert len(audited) == 1
    assert audited[0]["kind"] == "stop"
    assert audited[0]["reason"]
    # A stop decision never records a retry observation.
    assert [item for item in state.observations if item.summary == "reobserve_for_recovery"] == []


def test_retry_decision_emits_a_recover_audit_event():
    tool = _BaseFailingTool(failures=1)
    events = []
    state = run_tool(tool, progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "completed"
    audited = recovery_events(events)
    assert [item["kind"] for item in audited] == ["retry_after_delay"]
    assert tool.calls == ["open page", "open page"]


def test_reobserve_decision_takes_a_fresh_observation():
    tool = ObservingTool(failures=2)
    events = []
    state = run_tool(tool, progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "completed"
    # Initial pre-action observation + one fresh observation on the reobserve decision.
    assert tool.observe_calls == 2
    assert [item["kind"] for item in recovery_events(events)] == ["retry_after_delay", "reobserve"]
    assert [item.data["kind"] for item in recovery_decisions(state)] == ["retry_after_delay", "reobserve"]
    assert tool.calls == ["open page"] * 3


def test_replan_decision_reobserves_and_redecides():
    tool = DecidingTool(failures=2)
    events = []
    state = run_tool(tool, progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "completed"
    assert tool.observe_calls == 2
    assert tool.adapt_calls == 2  # original decision + one bounded replan decision
    assert [item["kind"] for item in recovery_events(events)] == ["retry_after_delay", "replan"]
    decisions = [item for item in state.observations if item.summary == "decision"]
    assert len(decisions) == 2
    assert tool.calls == ["open page"] * 3


def test_recovery_never_exceeds_the_step_budget():
    tool = ObservingTool(failures=99)
    state = run_tool(tool)
    assert state.status == "failed"
    assert len(tool.calls) == 3  # initial + IDEMPOTENT_STEP_RETRIES bounded retries
    kinds = [item.data["kind"] for item in recovery_decisions(state)]
    assert kinds == ["retry_after_delay", "reobserve", "stop"]
    assert state.error == "transient read-only failure"


# --- loop: delays are short and interruptible --------------------------------


def test_recovery_delay_is_short_and_applied_before_a_retry():
    tool = ObservingTool(failures=1)
    started = time.monotonic()
    state = run_tool(tool)
    elapsed = time.monotonic() - started
    assert state.status == "completed"
    assert tool.calls == ["open page", "open page"]
    assert elapsed >= RETRY_DELAY_SECONDS  # the bounded delay happened
    assert elapsed < 5.0


def test_recovery_delay_is_interruptible_by_stop():
    stop = Event()
    tool = ObservingTool(failures=99, on_fail=lambda: Timer(0.05, stop.set).start())
    loop = loop_for(tool)
    started = time.monotonic()
    state = loop.run("stopped during delay", [], stop_event=stop)
    elapsed = time.monotonic() - started
    assert tool.calls == ["open page"]  # no retry after stop interrupts the delay
    assert elapsed < RETRY_DELAY_SECONDS  # stop ended the wait early
    assert [item.data["kind"] for item in recovery_decisions(state)] == ["retry_after_delay"]


# --- loop: ask hands the run to a human --------------------------------------


def test_ask_decision_hands_the_run_to_a_human():
    tool = ObservingTool(failures=99, message="Permission denied by the local application.")
    events = []
    state = run_tool(tool, progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "waiting_confirmation"
    assert state.tool_history[0]["status"] == "waiting_confirmation"
    assert tool.calls == ["open page"]  # no automatic retry after asking
    audited = recovery_events(events)
    assert [item["kind"] for item in audited] == ["ask"]
    assert [item.data["kind"] for item in recovery_decisions(state)] == ["ask"]
    assert any(event == "waiting_approval" for event, _i, _d in events)


# --- integration: audit trail in a real run -----------------------------------


def test_lifecycle_audit_events_are_recorded_in_a_real_run(client, account_demo_url):
    plan = client.post("/api/agent/plan", json={"request": "Create an account for Demo User", "variables": {"url": account_demo_url, "email": "not-an-email"}}).json()
    created = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
    final = wait_status(client, created["run_id"], "failed", timeout=60)
    assert "could not be verified" in (final.get("error") or "")

    activity = client.get("/api/activity", params={"limit": 500}).json()
    events = [item["event"] for item in activity]
    for expected in ("observe", "decide", "verify", "recover"):
        assert expected in events, expected
    recover_details = [item["detail"] for item in activity if item["event"] == "recover"]
    assert any("stop" in detail for detail in recover_details), "the verification failure must be audited as a stop"
