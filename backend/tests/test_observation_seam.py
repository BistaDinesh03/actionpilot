"""Observation-before-action seam (Milestone B).

Before every agent action the loop records a bounded, read-only observation
of the live environment (observe -> decide -> act), each observation is
associated with its run/step, observations never occur once a run is
terminal, and the existing local-account execution and approval flows stay
green. Nothing here performs computer vision, LLM calls, or network capture
beyond the already-local page read.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app import main
from app.services.agent.browser_tool import BrowserTool
from app.services.agent.loop import AgentLoop
from app.services.agent.models import AgentPlan, AgentRequest, PlanStep, ToolResult
from app.services.agent.observer import MAX_BUTTONS, MAX_ELEMENTS, MAX_FIELD, MAX_FORMS, MAX_LINKS, MAX_VISIBLE_TEXT, observe_page
from app.services.agent.registry import ToolRegistry
from app.services.agent.state import Observation

ROOT = Path(__file__).resolve().parents[2]
REQUEST = "Open the local account demo and create an account for Demo User"


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
    raise AssertionError(f"run {run_id} never reached {wanted}; last status={state['status']}")


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


class OrderedTool:
    """Records the observe/execute ordering the seam guarantees."""

    name = "ordered"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self, execute_result=None):
        self.calls = []
        self.execute_result = execute_result

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def observe(self, plan):
        self.calls.append(f"observe:{plan.action}")
        return Observation(kind="browser", summary=f"state before {plan.action}", data={"available": True, "url": "http://127.0.0.1/"})

    def execute(self, plan, approved=False):
        self.calls.append(f"execute:{plan.action}")
        if self.execute_result is not None:
            return self.execute_result
        return ToolResult(status="completed", output={"action": plan.action})


def loop_for(steps, tool=None):
    registry = ToolRegistry()
    registry.register(tool or OrderedTool())
    return AgentLoop(FakeAgent(steps), registry)


def ordered_step(action):
    return PlanStep(tool="ordered", action=action, parameters={})


# --- unit: ordering + association -------------------------------------------


def test_observation_happens_before_the_action():
    tool = OrderedTool()
    state = loop_for([ordered_step("click save")], tool).run("one step", [])
    assert state.status == "completed"
    assert tool.calls == ["observe:click save", "execute:click save"]
    summaries = [item.summary for item in state.observations]
    assert summaries == ["planning_next_step", "action_observation", "completed"]


def test_observations_and_results_are_associated_with_their_step():
    tool = OrderedTool()
    state = loop_for([ordered_step("first"), ordered_step("second")], tool).run("two steps", [])
    action_steps = [item.data["step_index"] for item in state.observations if item.summary == "action_observation"]
    result_steps = [item.data["step_index"] for item in state.observations if item.summary in {"completed", "failed"}]
    assert action_steps == [0, 1]
    assert result_steps == [0, 1]
    # Per-step ordering: observe strictly precedes the step result.
    for step_index in (0, 1):
        observe_position = next(i for i, item in enumerate(state.observations) if item.summary == "action_observation" and item.data["step_index"] == step_index)
        result_position = next(i for i, item in enumerate(state.observations) if item.summary == "completed" and item.data["step_index"] == step_index)
        assert observe_position < result_position
    # notify("observe") carries the same association to the progress layer.
    assert [item.data["step_index"] for item in state.observations if item.summary == "action_observation"] == [0, 1]


def test_observe_notify_progress_event_is_emitted_with_step_index():
    events = []
    loop_for([ordered_step("only")], OrderedTool()).run("x", [], progress=lambda event, index, data: events.append((event, index, data)))
    observe_events = [(event, index, data) for event, index, data in events if event == "observe"]
    assert len(observe_events) == 1
    event, index, data = observe_events[0]
    assert index == 0
    assert data["step_index"] == 0
    assert data["step"]["label"] == "only"
    # Observe fires before the action lifecycle events.
    names = [event for event, _index, _data in events]
    assert names.index("observe") < names.index("step_started")


# --- unit: terminal runs never observe --------------------------------------


def test_no_observation_after_run_reaches_a_terminal_failure():
    class FailFirstStep(OrderedTool):
        def execute(self, plan, approved=False):
            self.calls.append(f"execute:{plan.action}")
            # Mutating step: fails with zero retries, run terminates immediately.
            return ToolResult(status="failed", message="target gone")

    tool = FailFirstStep()
    steps = [
        PlanStep(tool="ordered", action="submit form", parameters={"phase": "submit"}),
        PlanStep(tool="ordered", action="later step", parameters={}),
        PlanStep(tool="ordered", action="final step", parameters={}),
    ]
    state = loop_for(steps, tool).run("doomed", [])
    assert state.status == "failed"
    assert tool.calls == ["observe:submit form", "execute:submit form"]
    assert [item.data["step_index"] for item in state.observations if item.summary == "action_observation"] == [0]


def test_no_observation_when_run_is_already_terminal():
    from threading import Event

    tool = OrderedTool()
    stop = Event()
    stop.set()
    state = loop_for([ordered_step("never")], tool).run("stopped", [], stop_event=stop)
    assert state.status == "stopped"
    assert tool.calls == []
    assert [item.summary for item in state.observations] == []


# --- unit: bounded capture ---------------------------------------------------


def test_observation_is_bounded_on_a_large_page():
    html = (
        "<html><head><title>Bounds</title></head><body><p>"
        + ("lorem ipsum dolor sit amet " * 400)
        + "</p>"
        + "".join(f'<button id="b{i}">Button {i}</button>' for i in range(100))
        + "".join(f'<a href="/l{i}">Link {i}</a>' for i in range(100))
        + "".join(f'<input id="f{i}" placeholder="Field {i}">' for i in range(50))
        + "</body></html>"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        observation = observe_page(page)
        browser.close()

    data = observation.data
    assert len(data["visible_text"]) <= MAX_VISIBLE_TEXT
    assert len(data["links"]) <= MAX_LINKS
    assert len(data["buttons"]) <= MAX_BUTTONS
    assert len(data["forms"]) <= MAX_FORMS
    assert len(data["elements"]) <= MAX_ELEMENTS
    assert data["elements_total"] > MAX_ELEMENTS
    assert data["elements_truncated"] is True
    for element in data["elements"]:
        assert len(element["name"]) <= MAX_FIELD
        assert len(element["label"]) <= MAX_FIELD
    # Typed input values are never captured (only submit-like labels are).
    assert all("lorem" not in element["name"] for element in data["elements"])


def test_observation_exposes_deterministic_control_facts():
    html = (
        '<html><head><title>Controls</title></head><body>'
        '<form><label for="name">Full name</label><input id="name" placeholder="Ada">'
        '<button id="submitBtn" type="submit">Submit</button>'
        '<button id="hiddenBtn" style="display:none">Hidden</button></form>'
        "</body></html>"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        observation = observe_page(page)
        browser.close()
    elements = {element["id"]: element for element in observation.data["elements"]}
    assert elements["submitBtn"]["role"] == "button"
    assert elements["submitBtn"]["name"] == "Submit"
    assert elements["submitBtn"]["visible"] is True
    assert elements["hiddenBtn"]["visible"] is False
    assert elements["name"]["label"] == "Full name"
    assert observation.data["elements_truncated"] is False


# --- unit: BrowserTool observe is side-effect free ---------------------------


def test_browser_observe_without_a_session_is_an_honest_stub(tmp_path):
    tool = BrowserTool(tmp_path)
    step = PlanStep(tool="browser", action="Open the local account demo page", parameters={"session_id": "abc", "phase": "open", "url": "http://127.0.0.1:9/"})
    observation = tool.observe(step)
    assert observation is not None
    assert observation.data == {"available": False}
    assert tool._sessions == {}  # observing never opens a session


# --- integration: observations persist in the run record ---------------------


def test_observations_are_persisted_and_ordered_for_every_run_step(client, account_demo_url):
    plan = client.post("/api/agent/plan", json={"request": REQUEST, "variables": {"url": account_demo_url}}).json()
    created = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
    final = wait_status(client, created["run_id"], "completed")

    observations = final["output"]["observations"]
    actions = {item["data"]["step_index"]: item for item in observations if item["summary"] == "action_observation"}
    assert set(actions) == {0, 1, 2, 3}

    # Step 0 observes before any session exists; later steps observe the live page.
    assert actions[0]["data"]["available"] is False
    for step_index in (1, 2, 3):
        data = actions[step_index]["data"]
        assert data["available"] is True
        assert (data["url"] or "").startswith("http://127.0.0.1:")
        assert len(data["visible_text"]) <= MAX_VISIBLE_TEXT

    # observe -> act ordering is visible in the persisted record.
    for step_index in range(4):
        observe_position = next(i for i, item in enumerate(observations) if item["summary"] == "action_observation" and item["data"].get("step_index") == step_index)
        result_position = next(i for i, item in enumerate(observations) if item["summary"] in {"completed", "failed"} and item["data"].get("step_index") == step_index)
        assert observe_position < result_position

    # The run record itself is JSON-serializable and unchanged in shape.
    json.dumps(final["output"])
    # Observations freeze once the run is terminal.
    frozen = len(observations)
    time.sleep(0.5)
    after = client.get(f"/api/runs/{created['run_id']}").json()
    assert after["status"] == "completed"
    assert len(after["output"]["observations"]) == frozen
