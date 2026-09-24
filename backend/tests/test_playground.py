"""ActionPilot Playground — local adaptive execution proving ground.

Six deterministic scenarios served from playground-site/ drive the EXISTING
adaptive loop end to end — observe -> decide -> runtime risk -> act -> fresh
observation -> VerificationResult -> bounded recovery -> existing approval
gate -> completed/failed with evidence — with no AI, no cloud, no external
sites, no vision, and no real accounts.

Coverage map:
  1. normal completion ................ test_scenario1_normal_completion
  2. target change / re-target ........ test_scenario2_target_change_forces_deterministic_retarget
  3. verification delay ............... test_scenario3_verification_is_a_distinct_bounded_phase
     verification failure ............. test_scenario3_verification_wait_fails_honestly_when_bounded_out
  4. bounded recovery success ......... test_scenario4_bounded_recovery_retargets_and_succeeds
  5. approval required ................ test_scenario5_risk_escalation_waits_for_existing_approval_gate
  6. approval denied .................. test_scenario5_denied_approval_stops_safely
                                        (+ test_scenario5_approved_action_executes_and_verifies)
  7. bounded terminal failure ......... test_scenario6_terminal_failure_stops_at_the_retry_budget
  8. no infinite retries .............. test_scenario6_* (exact call/recovery counts)
                                        test_playground_steps_use_existing_budgets_and_high_risk_never_retries
  9. existing demo unchanged .......... test_existing_demo_and_research_fixtures_are_unchanged
 10. existing adaptive tests green .... full backend suite (quality gate)

No test contains arbitrary sleeps; every state transition is an explicit
deterministic page state or a fixed bounded wait handled by Playwright.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app.services.agent.loop import (
    IDEMPOTENT_STEP_RETRIES,
    RUN_RECOVERY_ATTEMPTS,
    AgentLoop,
    is_idempotent_step,
)
from app.services.agent.models import MAX_RETARGETS, AgentPlan, PlanStep
from app.services.agent.playground_tool import PlaygroundTool
from app.services.agent.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
PLAYGROUND = ROOT / "playground-site"
SID = "pg"


# --- fixtures ---------------------------------------------------------------


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="playground", confidence=1.0, steps=self.steps)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def playground_base():
    """Serve playground-site/ on an ephemeral local port (no long-running server)."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(PLAYGROUND)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PLAYGROUND),
    )
    started = False
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + "/index.html", timeout=0.5) as response:
                if response.status == 200:
                    started = True
                    break
        except Exception:
            time.sleep(0.05)
    try:
        assert started, "playground server did not start"
        yield base
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def tool(tmp_path):
    pg_tool = PlaygroundTool(tmp_path / "playground")
    yield pg_tool
    pg_tool.close_sessions()


# --- helpers ----------------------------------------------------------------


def scenario_url(base: str, name: str) -> str:
    return f"{base}/playground.html?scenario={name}"


def pstep(label: str, parameters: dict, sid: str = SID) -> PlanStep:
    return PlanStep(tool="playground", action=label, risk="low", parameters={"session_id": sid, **parameters})


def open_step(url: str, scenario: str | None = None, sid: str = SID) -> PlanStep:
    parameters: dict = {"action": "open", "url": url}
    if scenario is not None:
        parameters["scenario"] = scenario
    return pstep("Open the playground scenario", parameters, sid=sid)


def fill_step(fields: list, sid: str = SID) -> PlanStep:
    return pstep("Fill the playground form with synthetic values", {"action": "fill", "fields": fields}, sid=sid)


def click_step(label: str, target_name: str | None = None, target_css: str | None = None, sid: str = SID) -> PlanStep:
    target = {"name": target_name} if target_name else {"css": target_css}
    return pstep(label, {"action": "click", "target": target}, sid=sid)


def verify_step(expect: dict, wait_for: dict | None = None, label: str = "Verify the playground state", sid: str = SID) -> PlanStep:
    return pstep(label, {"action": "verify", "expect": expect, "wait_for": wait_for or {}}, sid=sid)


def run_loop(tool, steps, gate=None, progress=None):
    registry = ToolRegistry()
    registry.register(tool)
    loop = AgentLoop(FakeAgent(steps), registry)
    return loop.run("playground", [], gate=gate, progress=progress)


def open_scenario(tool, url: str, scenario: str | None = None, sid: str = SID):
    result = tool.execute(open_step(url, scenario=scenario, sid=sid))
    assert result.status == "completed", getattr(result, "message", "")
    return result


def summaries(state) -> list[str]:
    return [item.summary for item in state.observations]


def observation_data(state, summary: str) -> list[dict]:
    return [item.data for item in state.observations if item.summary == summary]


def recovery_kinds(state) -> list[str]:
    return [data["kind"] for data in observation_data(state, "recovery_decision")]


def page_state(tool, sid: str) -> dict:
    page = tool.page_for(sid)
    assert page is not None, f"no page for session {sid}"
    return page.evaluate("() => window.__playground.state")


def completed_results(state) -> list[dict]:
    return observation_data(state, "completed")


# --- scenario 1: normal form completion -------------------------------------


def test_scenario1_normal_completion(tool, playground_base):
    url = scenario_url(playground_base, "normal")
    events = []
    steps = [
        open_step(url, scenario="normal"),
        fill_step(
            [
                {"name": "name", "target": {"id": "pf-name"}, "kind": "text", "value": "Demo User"},
                {"name": "email", "target": {"id": "pf-email"}, "kind": "text", "value": "demo.user@example.com"},
                {"name": "country", "target": {"id": "pf-country"}, "kind": "select", "value": "de"},
                {"name": "terms", "target": {"id": "pf-terms"}, "kind": "checkbox", "value": True},
            ]
        ),
        click_step("Submit the playground form", target_name="Submit"),
        verify_step(
            expect={
                "stage": "submitted",
                "status": "Submitted.",
                "submitted_name": "Demo User",
                "submitted_email": "demo.user@example.com",
                "submitted_country": "Germany",
                "terms_accepted": True,
            },
            label="Verify the submitted result",
        ),
    ]

    state = run_loop(tool, steps, progress=lambda event, index, data: events.append(event))

    assert state.status == "completed"
    assert [item["status"] for item in state.tool_history] == ["completed"] * 4
    # Every completed action carries structured verification with local evidence.
    results = completed_results(state)
    assert len(results) == 4
    for result in results:
        verification = result["verification"]
        assert verification["passed"] is True
        assert verification["checks"], "verification must contain explicit checks"
        assert Path(verification["evidence"][0]).exists(), "screenshot evidence must exist on disk"
    # Field read-back checks prove the fill actually took effect.
    fill_checks = {check["name"]: check["passed"] for check in results[1]["verification"]["checks"]}
    assert set(fill_checks) == {"field_name", "field_email", "field_country", "field_terms"}
    assert all(fill_checks.values())
    # Observe -> decide -> verify seams all fired; nothing needed recovery.
    assert "observe" in events and "decide" in events and "verify" in events
    assert events.count("step_completed") == 4
    assert "recover" not in events
    assert observation_data(state, "runtime_risk") == []  # no approval path on the happy path
    decisions = observation_data(state, "decision")
    assert [decision["kind"] for decision in decisions] == ["execute"] * 4
    assert page_state(tool, SID)["stage"] == "submitted"


# --- scenario 2: target changes ---------------------------------------------


def test_scenario2_target_change_forces_deterministic_retarget(tool, playground_base):
    url = scenario_url(playground_base, "target-change")
    open_scenario(tool, url, scenario="target-change")

    # Teach-time initial observation: the planned control is "Continue".
    teach = tool.observe(click_step("Continue through the playground scenario", target_name="Continue"))
    teach_names = [element.get("name") for element in teach.data["elements"] if element.get("visible")]
    assert teach.data["scenario_state"]["targetLabel"] == "Continue"
    assert "Continue" in teach_names

    # A deterministic UI change between teaching and execution renames the target.
    applied = tool.page_for(SID).evaluate("() => window.__playground.mutate('stale-target')")
    assert applied["ok"] is True
    assert page_state(tool, SID)["targetLabel"] == "Continue to account"

    state = run_loop(
        tool,
        [
            click_step("Continue through the playground scenario", target_name="Continue"),
            verify_step(expect={"stage": "continued", "status": "Continued."}, label="Verify the continued state"),
        ],
    )

    assert state.status == "completed"
    decisions = observation_data(state, "decision")
    # Deterministic re-target from a fresh observation — no fuzzy matching.
    retargets = [decision for decision in decisions if decision["kind"] == "retarget"]
    assert len(retargets) == 1
    assert retargets[0]["replans"] == MAX_RETARGETS
    assert retargets[0]["target"]["css"] == "#pf-next"
    assert "uniquely matched" in retargets[0]["reason"]
    assert decisions[-1]["kind"] == "execute"  # the verify step had no semantic target
    assert page_state(tool, SID)["stage"] == "continued"
    # open + click + verify, no more: the re-target happened inside the decision seam.
    assert tool.execute_calls == 3
    assert observation_data(state, "recovery_decision") == []


# --- scenario 3: verification delay / distinct phase -------------------------


def test_scenario3_verification_is_a_distinct_bounded_phase(tool, playground_base):
    url = scenario_url(playground_base, "verify-delay")
    open_scenario(tool, url, scenario="verify-delay")
    events = []

    state = run_loop(
        tool,
        [
            click_step("Save the playground state", target_name="Save"),
            verify_step(
                expect={"stage": "saved", "status": "Saved successfully", "saved": True},
                wait_for={"saved": True},
                label="Verify the saved outcome",
            ),
        ],
        progress=lambda event, index, data: events.append(event),
    )

    assert state.status == "completed"
    assert [item["status"] for item in state.tool_history] == ["completed"] * 2
    results = completed_results(state)
    click_result, verify_result = results[0], results[1]
    # The ACTION succeeded while the outcome was still in progress.
    assert click_result["verification"]["passed"] is True
    assert "Saving…" in click_result["verification"]["summary"]
    # VERIFICATION is a separate phase: it re-observed (bounded, exactly once)
    # and only then judged the final state.
    assert verify_result["verification"]["passed"] is True
    assert verify_result["reobservations"] == 1
    assert isinstance(verify_result["first_read"], dict) and "status" in verify_result["first_read"]
    assert verify_result["scenario_state"]["saved"] is True
    assert events.count("verify") == 2  # one verification per step, distinct from actions
    assert observation_data(state, "recovery_decision") == []
    assert tool.execute_calls == 3  # pre-open + click + verify: the bounded wait lived inside verification


def test_scenario3_verification_wait_fails_honestly_when_bounded_out(tool, playground_base):
    url = scenario_url(playground_base, "verify-delay")
    open_scenario(tool, url, scenario="verify-delay")

    # No Save click: the outcome never arrives; the bounded wait must fail honestly.
    state = run_loop(
        tool,
        [verify_step(expect={"saved": True}, wait_for={"saved": True}, label="Verify an outcome that never arrives")],
    )

    assert state.status == "failed"
    assert "could not be verified" in state.error
    assert recovery_kinds(state) == ["stop"]  # a failed verification never retries
    assert observation_data(state, "reobserve_for_recovery") == []
    assert tool.execute_calls == 2  # pre-open + a single verification attempt: no repeats
    failed = observation_data(state, "failed")[0]
    assert failed["verification"]["passed"] is False
    assert failed["first_read"]["status"] == "Idle."
    assert Path(failed["verification"]["evidence"][0]).exists()


# --- scenario 4: bounded recovery -------------------------------------------


def test_scenario4_bounded_recovery_retargets_and_succeeds(tool, playground_base):
    url = scenario_url(playground_base, "recovery")
    open_scenario(tool, url, scenario="recovery")

    state = run_loop(
        tool,
        [
            click_step("Save the playground draft", target_name="Save"),
            verify_step(expect={"stage": "recovered", "attempts": 2}, label="Verify the recovered state"),
        ],
    )

    assert state.status == "completed"
    # failure -> bounded recovery decision -> fresh observation/re-target -> retry -> success
    assert recovery_kinds(state) == ["retry_after_delay", "replan"]
    assert len(observation_data(state, "reobserve_for_recovery")) == 2
    retargets = [d for d in observation_data(state, "decision") if d["kind"] == "retarget"]
    assert len(retargets) == 1
    assert retargets[0]["target"]["css"] == "#pf-alternate"
    # Exactly one extra execution beyond the retry/replan attempts: 3 click
    # calls + 1 pre-open + 1 verify step.
    assert tool.execute_calls == 5
    final = page_state(tool, SID)
    assert final["stage"] == "recovered"
    assert final["attempts"] == 2
    assert [item["status"] for item in state.tool_history] == ["completed", "completed"]


# --- scenario 5: approval ----------------------------------------------------


APPROVAL_STEPS = "Submit the application to the local playground"


def test_scenario5_risk_escalation_waits_for_existing_approval_gate(tool, playground_base):
    url = scenario_url(playground_base, "approval")
    events = []

    state = run_loop(
        tool,
        [open_step(url, scenario="approval"), click_step(APPROVAL_STEPS, target_name="Send application")],
        progress=lambda event, index, data: events.append(event),
    )

    # plan (low risk) -> runtime risk escalation from the fresh observation -> gate
    escalations = observation_data(state, "runtime_risk")
    assert escalations == [{"step_index": 1, "action": APPROVAL_STEPS, "producer": "low", "runtime": "high"}]
    approvals = observation_data(state, "approval_required")
    assert len(approvals) == 1 and approvals[0]["action"] == APPROVAL_STEPS
    assert state.status == "waiting_confirmation"
    # Without a gate there is no waiting_approval event — the run waits honestly.
    assert "waiting_approval" not in events
    # The step stops AT the existing gate: it never executes without approval.
    assert tool.execute_calls == 1  # open only
    assert [item["status"] for item in state.tool_history] == ["completed"]  # open completed, send never ran
    assert page_state(tool, SID)["stage"] == "draft"


def test_scenario5_approved_action_executes_and_verifies(tool, playground_base):
    url = scenario_url(playground_base, "approval")
    gate_calls = []
    events = []

    def gate(index, step_data):
        gate_calls.append(index)
        return None  # operator approves

    state = run_loop(
        tool,
        [open_step(url, scenario="approval"), click_step(APPROVAL_STEPS, target_name="Send application")],
        gate=gate,
        progress=lambda event, index, data: events.append((event, index)),
    )

    assert state.status == "completed"
    # The harmless open step is not gated; only the escalated send step is.
    assert gate_calls == [1]
    assert observation_data(state, "approval_granted") == [{"action": APPROVAL_STEPS}]
    assert ("waiting_approval", 1) in events
    click_results = [result for result in completed_results(state) if result["action"] == "click"]
    assert len(click_results) == 1
    assert click_results[0]["verification"]["passed"] is True
    assert click_results[0]["approved"] is True
    assert page_state(tool, SID)["stage"] == "sent"
    assert ("verify", 0) in events or ("verify", 1) in events


def test_scenario5_denied_approval_stops_safely(tool, playground_base):
    url = scenario_url(playground_base, "approval")
    gate_calls = []
    denial = "Operator denied the playground action."

    def gate(index, step_data):
        gate_calls.append(index)
        return denial

    state = run_loop(tool, [open_step(url, scenario="approval"), click_step(APPROVAL_STEPS, target_name="Send application")], gate=gate)

    assert state.status == "stopped"
    assert state.error == denial
    assert gate_calls == [1]
    rejections = observation_data(state, "approval_rejected")
    assert rejections == [{"reason": denial, "action": APPROVAL_STEPS}]
    # Denied means never executed: the page is untouched and no click happened.
    assert tool.execute_calls == 1
    assert page_state(tool, SID)["stage"] == "draft"
    assert [item["status"] for item in state.tool_history] == ["completed"]


# --- scenario 6: terminal failure / bounds -----------------------------------


def test_scenario6_terminal_failure_stops_at_the_retry_budget(tool, playground_base):
    url = scenario_url(playground_base, "failure")
    open_scenario(tool, url, scenario="failure")

    state = run_loop(tool, [click_step("Try the playground action again", target_name="Try again")])

    assert state.status == "failed"
    assert "Persistent deterministic failure" in state.error
    assert recovery_kinds(state) == ["retry_after_delay", "replan", "stop"]
    assert len(observation_data(state, "reobserve_for_recovery")) == IDEMPOTENT_STEP_RETRIES
    # Exactly 1 pre-open + 1 initial + 2 bounded retries — then the run stops.
    assert tool.execute_calls == 4
    final = page_state(tool, SID)
    assert final["stage"] == "failed-permanent"
    assert final["attempts"] == 3
    assert [item["status"] for item in state.tool_history] == ["failed"]
    # Structured evidence survives: the failed result still records the state.
    failed = observation_data(state, "failed")[0]
    assert failed["scenario_state"]["attempts"] == 3
    assert Path(failed["screenshot_path"]).exists()


def test_scenario6_run_global_recovery_cap_is_enforced(tool, playground_base):
    recovery_url = scenario_url(playground_base, "recovery")
    failure_url = scenario_url(playground_base, "failure")
    # Three sessions in parallel deterministic states: two recoverable cycles
    # that consume the run budget, then a step that fails while the cap hits.
    open_scenario(tool, recovery_url, scenario="recovery", sid="a")
    open_scenario(tool, recovery_url, scenario="recovery", sid="b")
    open_scenario(tool, failure_url, scenario="failure", sid="c")

    state = run_loop(
        tool,
        [
            click_step("Recover the first playground scenario", target_name="Save", sid="a"),
            click_step("Recover the second playground scenario", target_name="Save", sid="b"),
            click_step("Fail the third playground scenario", target_name="Try again", sid="c"),
        ],
    )

    assert state.status == "failed"
    # Two recoverable steps consumed 2+2 attempts; the third got only its first
    # retry because the RUN-GLOBAL cap stopped recovery. Nothing exceeded it.
    assert len(observation_data(state, "reobserve_for_recovery")) == RUN_RECOVERY_ATTEMPTS
    assert len(observation_data(state, "recovery_decision")) == RUN_RECOVERY_ATTEMPTS
    assert set(recovery_kinds(state)) == {"retry_after_delay", "replan"}
    # 3 pre-opens + (3+3) recovered executions + 2 on the failing step.
    assert tool.execute_calls == 11
    assert [item["status"] for item in state.tool_history] == ["completed", "completed", "failed"]
    assert "Persistent deterministic failure" in state.error
    assert page_state(tool, "a")["stage"] == "recovered"
    assert page_state(tool, "b")["stage"] == "recovered"
    assert page_state(tool, "c")["attempts"] == 2  # initial + the single capped retry


# --- budgets / classification ------------------------------------------------


def test_playground_steps_use_existing_budgets_and_high_risk_never_retries():
    low = PlanStep(tool="playground", action="Try the playground action again", risk="low", parameters={"action": "click"})
    high = PlanStep(tool="playground", action="Submit the application", risk="high", parameters={"action": "click"})
    assert is_idempotent_step(low) is True
    assert is_idempotent_step(high) is False  # high-risk steps never auto-retry
    # The playground runs on the EXISTING budgets; none were raised.
    assert IDEMPOTENT_STEP_RETRIES == 2
    assert RUN_RECOVERY_ATTEMPTS == 5


# --- demo separation / scope -------------------------------------------------


def test_existing_demo_and_research_fixtures_are_unchanged():
    html = (ROOT / "demo-site" / "account.html").read_text(encoding="utf-8")
    for marker in (
        'id="fullName"',
        'id="email"',
        'id="terms"',
        'id="country"',
        'id="submitBtn"',
        'id="result"',
        'id="sumName"',
        'id="sumEmail"',
        'id="sumType"',
        'id="sumCountry"',
        'name="accountType"',
        "Enter a valid email address",
    ):
        assert marker in html, f"demo contract marker missing: {marker}"
    # The protected demo is completely unaware of the playground.
    for demo_file in sorted((ROOT / "demo-site").glob("*.html")):
        assert "playground" not in demo_file.read_text(encoding="utf-8").lower(), demo_file.name
    # The research test-site fixture keeps its original contract too.
    research = (ROOT / "agent-test-site" / "index.html").read_text(encoding="utf-8")
    assert "AI Automation Articles" in research
    assert "playground" not in research.lower()


def test_playground_site_has_no_external_dependencies():
    for name in ("index.html", "playground.html", "app.js", "styles.css"):
        content = (PLAYGROUND / name).read_text(encoding="utf-8")
        assert "http://" not in content, name
        assert "https://" not in content, name
