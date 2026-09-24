"""Structured verification seam (Milestone D).

Every completed agent action carries a VerificationResult built from
deterministic checks against local evidence (passed, checks, summary,
evidence). A run never claims success merely because an action executed
without throwing: a completed action whose verification failed is turned
into a truthful run failure by the loop.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

from app.services.agent.browser_tool import BrowserTool
from app.services.agent.loop import AgentLoop
from app.services.agent.models import AgentPlan, PlanStep, ToolResult, VerificationResult
from app.services.agent.registry import ToolRegistry
from app.services.desktop.tool import DesktopTool

ROOT = Path(__file__).resolve().parents[2]


# --- helpers -----------------------------------------------------------------


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


class VerifyTool:
    """Returns a fixed result carrying a structured verification."""

    name = "verifyfake"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self, verification):
        self.verification = verification

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def execute(self, plan, approved=False):
        return ToolResult(status="completed", output={"verification": self.verification})


def loop_for(tool):
    registry = ToolRegistry()
    registry.register(tool)
    step = PlanStep(tool="verifyfake", action="check the outcome", parameters={})
    return AgentLoop(FakeAgent([step]), registry)


def run_with_events(tool):
    events = []
    state = loop_for(tool).run("verify", [], progress=lambda event, index, data: events.append((event, index, data)))
    return state, events


# --- unit: structured result shape -------------------------------------------


def test_verification_result_is_structured_and_json_serializable():
    result = VerificationResult.from_checks(
        {"page_reached": True, "effect_observed": False},
        summary="mixed",
        evidence=["shot.png", "http://127.0.0.1:4173/account.html"],
        observed={"name": "Ada"},
        expected={"name": "Ada"},
        visible_errors=["Enter a valid email address"],
    )
    assert result.passed is False
    payload = result.model_dump()
    assert payload["checks"] == [
        {"name": "page_reached", "passed": True, "detail": None},
        {"name": "effect_observed", "passed": False, "detail": None},
    ]
    assert payload["evidence"] == ["shot.png", "http://127.0.0.1:4173/account.html"]
    json.dumps(payload)  # round-trips through the run record unchanged
    assert VerificationResult.from_checks({"a": True}).passed is True
    assert VerificationResult.from_checks({}).passed is False  # nothing proven


# --- loop: failed verification is a truthful failure --------------------------


def test_failed_verification_forces_a_truthful_run_failure():
    verification = VerificationResult.from_checks({"effect_observed": False}, summary="Not verified: the page showed no visible response.").model_dump()
    state, events = run_with_events(VerifyTool(verification))
    assert state.status == "failed"
    assert "Verification failed" in (state.error or "")
    assert "Not verified" in (state.error or "")
    assert state.tool_history[0]["status"] == "failed"
    # Evidence stays attached to the failed result for debugging.
    failed_observation = next(item for item in state.observations if item.summary == "failed")
    assert failed_observation.data["verification"]["passed"] is False
    names = [event for event, _index, _data in events]
    assert "step_failed" in names
    assert "step_completed" not in names


def test_passing_verification_does_not_fail_the_run():
    verification = VerificationResult.from_checks({"page_reached": True}, summary="Opened page.").model_dump()
    state, _events = run_with_events(VerifyTool(verification))
    assert state.status == "completed"
    assert state.tool_history[0]["status"] == "completed"


def test_verify_progress_event_reports_the_structured_result():
    verification = VerificationResult.from_checks({"page_reached": True}, summary="Opened page.").model_dump()
    _state, events = run_with_events(VerifyTool(verification))
    verify_events = [(index, data) for event, index, data in events if event == "verify"]
    assert len(verify_events) == 1
    index, data = verify_events[0]
    assert index == 0
    assert data["passed"] is True
    assert data["summary"] == "Opened page."
    assert data["step_index"] == 0
    names = [event for event, _index, _data in events]
    assert names.index("verify") < names.index("step_completed")


def test_failed_verification_still_emits_the_verify_event():
    verification = VerificationResult.from_checks({"observation_captured": False}, summary="Not verified: nothing was captured.").model_dump()
    _state, events = run_with_events(VerifyTool(verification))
    verify_events = [data for event, _index, data in events if event == "verify"]
    assert len(verify_events) == 1
    assert verify_events[0]["passed"] is False
    names = [event for event, _index, _data in events]
    assert names.index("verify") < names.index("step_failed")


# --- other completed actions carry verification too ---------------------------


def test_desktop_completed_action_has_structured_verification(tmp_path):
    plan = PlanStep(tool="desktop", action="Wait", parameters={"action": {"type": "wait", "value": "0"}})
    result = DesktopTool(tmp_path).execute(plan)
    assert result.status == "completed"
    verification = result.output["verification"]
    assert verification["passed"] is True
    assert verification["checks"][0]["name"] == "observation_captured"
    assert verification["summary"].startswith("Desktop observation captured")
    assert verification["evidence"]
    assert Path(verification["evidence"][0]).exists()
    json.dumps(verification)


# --- integration: real browser actions, real evidence -------------------------

DEMO_PAGE = (
    "<!doctype html><html><head><title>Verification demo</title></head><body>"
    "<h1>Verification demo</h1><form>"
    "<button id=\"submitBtn\" type=\"button\" onclick=\"document.getElementById('marker').style.display='block'\">Submit</button>"
    "</form><div id=\"marker\" style=\"display:none\">RESPONSE VISIBLE</div>"
    "</body></html>"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def demo_server(tmp_path):
    (tmp_path / "index.html").write_text(DEMO_PAGE, encoding="utf-8")
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 8
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/index.html", timeout=1) as response:
                ready = response.status == 200
            if ready:
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError("verification demo server did not become ready")
    yield base
    process.terminate()
    process.wait(timeout=5)


def test_completed_browser_actions_carry_structured_verification(demo_server, tmp_path):
    tool = BrowserTool(tmp_path)
    registry = ToolRegistry()
    registry.register(tool)
    session_id = uuid.uuid4().hex
    base = {"session_id": session_id, "url": f"{demo_server}/index.html"}
    steps = [
        PlanStep(tool="browser", action="Open the demo page", risk="low", parameters={**base, "phase": "open"}),
        PlanStep(tool="browser", action="Submit the account form", risk="low", parameters={**base, "phase": "submit"}),
    ]
    try:
        state = AgentLoop(FakeAgent(steps), registry).run("verify demo", [])
    finally:
        tool.close_sessions()
    assert state.status == "completed"
    completed = [item for item in state.observations if item.summary == "completed"]
    assert len(completed) == 2
    for observation in completed:
        verification = observation.data["verification"]
        assert verification["passed"] is True
        assert verification["checks"], "checks list must be present and non-empty"
        for check in verification["checks"]:
            assert {"name", "passed"} <= set(check)
        assert verification["summary"]
        assert verification["evidence"], "evidence must be present"
        assert Path(verification["evidence"][0]).exists(), "evidence must reference real local files"
    # Both verifications are associated with their steps.
    assert {item.data["step_index"] for item in completed} == {0, 1}
