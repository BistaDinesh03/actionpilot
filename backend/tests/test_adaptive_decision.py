"""Deterministic adaptive decision seam (Milestone C).

Observe -> decide -> act with no AI guessing: the planned step executes as
-is when the fresh observation still contains it, a bounded deterministic
re-target happens only when existing matching rules establish exactly one
safe match, ambiguous or missing targets fail honestly without acting, and
the decision seam can never loop indefinitely.
"""

import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.agent.browser_tool import BrowserTool
from app.services.agent.loop import IDEMPOTENT_STEP_RETRIES, AgentLoop
from app.services.agent.models import AgentPlan, Decision, MAX_RETARGETS, PlanStep, ToolResult
from app.services.agent.registry import ToolRegistry
from app.services.agent.state import Observation

ROOT = Path(__file__).resolve().parents[2]


# --- helpers -----------------------------------------------------------------


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


def submit_step():
    return PlanStep(
        tool="browser",
        action="Submit the account form",
        risk="low",
        parameters={"phase": "submit", "session_id": "s", "url": "http://127.0.0.1:9/"},
    )


def button(name, id=None, visible=True):
    """Element dict in the exact shape observer.observe_page produces."""
    return {"tag": "button", "role": "button", "id": id, "type": None, "placeholder": None, "name": name, "label": "", "visible": visible}


def observed(elements, *, available=True, truncated=False, total=None):
    return Observation(kind="browser", summary="synthetic", data={
        "available": available,
        "elements": elements,
        "elements_total": total if total is not None else len(elements),
        "elements_truncated": truncated,
    })


def loop_with(tool, step):
    registry = ToolRegistry()
    registry.register(tool)
    return AgentLoop(FakeAgent([step]), registry)


def decisions(state):
    return [item for item in state.observations if item.summary == "decision"]


# --- unit: decision rules ----------------------------------------------------


def test_unchanged_ui_uses_the_original_target(tmp_path):
    tool = BrowserTool(tmp_path)
    step = submit_step()
    observation = observed([button("Reset form", id="reset", visible=False), button("Submit", id="submitBtn")])
    adapted, decision = tool.adapt(step, observation)
    assert adapted is step  # planned step is still valid: no change at all
    assert decision.kind == "execute"
    assert decision.replans == 0
    assert "present in the fresh observation" in decision.reason


def test_small_deterministic_label_change_re_targets_safely(tmp_path):
    tool = BrowserTool(tmp_path)
    step = submit_step()
    adapted, decision = tool.adapt(step, observed([button("Create account", id="submitBtn")]))
    assert decision.kind == "retarget"
    assert decision.replans == MAX_RETARGETS == 1
    assert decision.target == {"css": "#submitBtn", "role": "button", "name": "Create account"}
    assert adapted is not step
    assert adapted.parameters["target"] == decision.target
    assert "target" not in step.parameters  # the original plan is never mutated


def test_missing_target_fails_bounded_without_guessing(tmp_path):
    tool = BrowserTool(tmp_path)
    adapted, decision = tool.adapt(submit_step(), observed([]))
    assert decision.kind == "fail"
    assert decision.reason.startswith("Target not found")
    assert decision.target is None
    assert decision.replans == 0
    assert "target" not in adapted.parameters


def test_ambiguous_target_never_guesses(tmp_path):
    tool = BrowserTool(tmp_path)
    adapted, decision = tool.adapt(submit_step(), observed([button("Create account", id="btnA"), button("Register now", id="btnB")]))
    assert decision.kind == "fail"
    assert "Ambiguous" in decision.reason
    assert decision.target is None
    assert "target" not in adapted.parameters


def test_control_without_a_stable_selector_fails_honestly(tmp_path):
    tool = BrowserTool(tmp_path)
    adapted, decision = tool.adapt(submit_step(), observed([button("", id=None)]))
    assert decision.kind == "fail"
    assert "no stable selector" in decision.reason
    assert "target" not in adapted.parameters


def test_unavailable_or_truncated_observations_never_change_the_plan(tmp_path):
    tool = BrowserTool(tmp_path)
    step = submit_step()
    _adapted, fallback = tool.adapt(step, observed([], available=False))
    assert fallback.kind == "execute"
    assert "No fresh observation" in fallback.reason
    _adapted, truncated = tool.adapt(step, observed([button("Submit", id="s")], truncated=True, total=999))
    assert truncated.kind == "execute"
    assert "truncated" in truncated.reason


def test_phases_without_semantic_targets_keep_the_original_plan(tmp_path):
    tool = BrowserTool(tmp_path)
    for phase in ("open", "fill", "verify", None):
        parameters = {"session_id": "s", "url": "http://127.0.0.1:9/"}
        if phase:
            parameters["phase"] = phase
        step = PlanStep(tool="browser", action=f"step {phase}", parameters=parameters)
        adapted, decision = tool.adapt(step, observed([button("Submit", id="s")]))
        assert adapted is step
        assert decision.kind == "execute"


def test_replans_are_structurally_capped():
    assert MAX_RETARGETS == 1
    assert Decision(kind="retarget", replans=1).replans == 1
    with pytest.raises(ValidationError):
        Decision(kind="retarget", replans=2)


# --- unit: the seam cannot loop ----------------------------------------------


class AlwaysRetargetTool:
    """A decision seam that would re-target every single time."""

    name = "browser"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self):
        self.adapt_calls = 0
        self.execute_calls = 0

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def observe(self, plan):
        return Observation(kind="browser", summary="page", data={
            "available": True,
            "elements": [button("Something", id="x")],
            "elements_total": 1,
            "elements_truncated": False,
        })

    def adapt(self, plan, observation):
        self.adapt_calls += 1
        adapted = plan.model_copy(deep=True)
        adapted.parameters["target"] = {"role": "button", "name": "Something"}
        return adapted, Decision(kind="retarget", reason="would always re-target", target=adapted.parameters["target"], replans=MAX_RETARGETS)

    def execute(self, plan, approved=False):
        self.execute_calls += 1
        return ToolResult(status="failed", message="the click target vanished")


def test_decision_seam_never_loops_for_mutating_steps():
    tool = AlwaysRetargetTool()
    state = loop_with(tool, submit_step()).run("doomed", [])
    assert state.status == "failed"
    assert tool.adapt_calls == 1  # decided once before acting, never in a loop
    assert tool.execute_calls == 1  # mutating step: zero automatic retries


def test_decision_seam_stays_bounded_under_idempotent_retries():
    tool = AlwaysRetargetTool()
    step = PlanStep(tool="browser", action="Open", risk="low", parameters={"phase": "open", "session_id": "s", "url": "http://127.0.0.1:9/"})
    state = loop_with(tool, step).run("doomed", [])
    assert state.status == "failed"
    assert tool.execute_calls == 1 + IDEMPOTENT_STEP_RETRIES  # hard retry bound
    # One initial decision plus at most one bounded replan decision taken
    # during recovery (Milestone E): the seam stays bounded, never looping.
    assert tool.adapt_calls == 2
    assert tool.adapt_calls <= 1 + IDEMPOTENT_STEP_RETRIES


# --- integration: real local pages, real browser ------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def button_page(button_text: str, marker: str) -> str:
    return (
        "<!doctype html><html><head><title>Decision demo</title></head><body>"
        "<h1>Decision demo</h1><form>"
        f"<button id=\"submitBtn\" type=\"button\" onclick=\"document.getElementById('marker').style.display='block'\">{button_text}</button>"
        f"</form><div id=\"marker\" style=\"display:none\">{marker}</div>"
        "</body></html>"
    )


AMBIGUOUS_PAGE = (
    "<!doctype html><html><head><title>Decision demo</title></head><body>"
    "<h1>Decision demo</h1>"
    "<button id=\"btnA\" type=\"button\">Create account</button>"
    "<button id=\"btnB\" type=\"button\">Register now</button>"
    "</body></html>"
)
EMPTY_PAGE = (
    "<!doctype html><html><head><title>Decision demo</title></head><body>"
    "<h1>Nothing to click here</h1>"
    "</body></html>"
)


@pytest.fixture
def page_server(tmp_path):
    (tmp_path / "unchanged.html").write_text(button_page("Submit", "SUBMITTED"), encoding="utf-8")
    (tmp_path / "changed.html").write_text(button_page("Create account", "CREATED"), encoding="utf-8")
    (tmp_path / "ambiguous.html").write_text(AMBIGUOUS_PAGE, encoding="utf-8")
    (tmp_path / "empty.html").write_text(EMPTY_PAGE, encoding="utf-8")
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
            with urllib.request.urlopen(base + "/unchanged.html", timeout=1) as response:
                ready = response.status == 200
            if ready:
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError("decision demo server did not become ready")
    yield base
    process.terminate()
    process.wait(timeout=5)


def run_submit_flow(tool, url):
    """Open + submit phases through the real loop. Returns (state, execute calls)."""
    registry = ToolRegistry()
    registry.register(tool)
    session_id = uuid.uuid4().hex
    base = {"session_id": session_id, "url": url}
    steps = [
        PlanStep(tool="browser", action="Open the demo page", risk="low", parameters={**base, "phase": "open"}),
        PlanStep(tool="browser", action="Submit the account form", risk="low", parameters={**base, "phase": "submit"}),
    ]
    calls = []
    original = tool.execute

    def counting_execute(plan, approved=False):
        calls.append(dict(plan.parameters))
        return original(plan, approved)

    tool.execute = counting_execute
    try:
        state = AgentLoop(FakeAgent(steps), registry).run("decision demo", [])
    finally:
        tool.close_sessions()
    return state, calls


def test_unchanged_page_clicks_the_planned_target(page_server, tmp_path):
    state, calls = run_submit_flow(BrowserTool(tmp_path), f"{page_server}/unchanged.html")
    assert state.status == "completed"
    step_decisions = {item.data["step_index"]: item.data for item in decisions(state)}
    assert step_decisions[1]["kind"] == "execute"
    assert "present in the fresh observation" in step_decisions[1]["reason"]
    assert len(calls) == 2  # open + exactly one planned click
    assert "SUBMITTED" in state.result["observation"]["data"]["visible_text"]


def test_changed_label_page_is_safely_re_targeted(page_server, tmp_path):
    state, calls = run_submit_flow(BrowserTool(tmp_path), f"{page_server}/changed.html")
    assert state.status == "completed"
    step_decisions = {item.data["step_index"]: item.data for item in decisions(state)}
    decision = step_decisions[1]
    assert decision["kind"] == "retarget"
    assert decision["replans"] == MAX_RETARGETS
    assert decision["target"] == {"css": "#submitBtn", "role": "button", "name": "Create account"}
    assert len(calls) == 2
    # The post-action observation proves the re-targeted click hit the right control.
    assert "CREATED" in state.result["observation"]["data"]["visible_text"]


def test_ambiguous_page_fails_without_acting(page_server, tmp_path):
    state, calls = run_submit_flow(BrowserTool(tmp_path), f"{page_server}/ambiguous.html")
    assert state.status == "failed"
    assert "Ambiguous" in (state.error or "")
    assert len(calls) == 1  # only the open step ever acted; no click happened
    assert [item["status"] for item in state.tool_history] == ["completed", "failed"]


def test_missing_target_fails_quickly_and_honestly(page_server, tmp_path):
    started = time.monotonic()
    state, calls = run_submit_flow(BrowserTool(tmp_path), f"{page_server}/empty.html")
    elapsed = time.monotonic() - started
    assert state.status == "failed"
    assert (state.error or "").startswith("Target not found")
    assert len(calls) == 1
    assert elapsed < 6  # bounded: fails from the observation, not a locator timeout
