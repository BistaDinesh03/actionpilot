from pathlib import Path
import subprocess
import sys
import time

from app.services.agent.loop import AgentLoop
from app.services.agent.browser_tool import BrowserTool
from app.services.agent.memory import MemoryStore
from app.services.agent.models import AgentPlan, AgentRequest, PlanStep, ToolResult
from app.services.agent.registry import ToolRegistry
from app.services.agent.routine import RoutineStore


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


class FakeTool:
    name = "fake"
    description = "test"
    capabilities = []
    risk_level = "low"

    def can_handle(self, request):
        return True

    def plan(self, request):
        return self.steps

    def execute(self, plan, approved=False):
        return ToolResult(status="completed", output={"action": plan.action})


def loop_with(steps, max_steps=15):
    registry = ToolRegistry()
    registry.register(FakeTool())
    return AgentLoop(FakeAgent(steps), registry, max_steps=max_steps)


def test_iterative_loop_records_observations_and_tool_history():
    steps = [PlanStep(tool="fake", action="search"), PlanStep(tool="fake", action="inspect"), PlanStep(tool="fake", action="summarize")]
    state = loop_with(steps).run("research", [])
    assert state.status == "completed"
    assert len(state.observations) == 6
    assert [item["action"] for item in state.tool_history] == ["search", "inspect", "summarize"]


def test_loop_enforces_maximum_steps():
    steps = [PlanStep(tool="fake", action=str(index)) for index in range(4)]
    state = loop_with(steps, max_steps=2).run("bounded", [])
    assert state.status == "failed"
    assert "Maximum" in (state.error or "")


def test_loop_stops_before_high_risk_plan():
    state = loop_with([PlanStep(tool="fake", action="send", risk="high")]).run("send", [])
    assert state.status == "waiting_confirmation"
    assert state.observations[0].kind == "tool_result"


def test_memory_store_explicit_crud(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    created = store.create("user_preference", "Content format", "Include a hook and why it may work")
    assert store.list()[0]["value"].startswith("Include")
    updated = store.update(created["id"], "Content format", "Include hook, why, and example", "user_preference")
    assert updated["value"].endswith("example")
    assert store.delete(created["id"]) is True
    assert store.list() == []


def test_routine_store_create_update_run_marker(tmp_path):
    store = RoutineStore(tmp_path / "routine.db")
    routine = store.create("Morning Research", "Research AI automation", "daily 09:00")
    assert routine["enabled"] is True
    store.mark_run(routine["id"])
    assert store.list()[0]["last_run"] is not None
    assert store.update(routine["id"], "Morning Research", "Research AI automation posts", "manual", False)["enabled"] is False


def test_browser_tool_observes_local_research_site():
    root = Path(__file__).resolve().parents[2]
    process = subprocess.Popen([sys.executable, "-m", "http.server", "4174", "--directory", str(root / "agent-test-site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        result = BrowserTool().execute(PlanStep(tool="browser", action="open", parameters={"url": "http://127.0.0.1:4174"}))
        assert result.status == "completed"
        assert "AI Automation Articles" in result.output["data"]["visible_text"]
        assert len(result.output["data"]["links"]) == 3
    finally:
        process.terminate()
        process.wait(timeout=5)
