"""Bounded per-step recovery (Milestone A).

Every step gets a fresh recovery budget, idempotent/read-only failures retry
at most twice, mutating/destructive failures never auto-retry, a run-global
cap of 5 recovery attempts is enforced, and no run can loop forever. The run
state machine, approvals, pause/resume/stop, and the replay engine are all
left untouched by this milestone.
"""

from threading import Event

from app.services.agent.loop import IDEMPOTENT_STEP_RETRIES, RUN_RECOVERY_ATTEMPTS, AgentLoop, is_idempotent_step
from app.services.agent.models import AgentPlan, AgentRequest, PlanStep, ToolResult
from app.services.agent.registry import ToolRegistry
from app.services.desktop.tool import DesktopTool


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


class ScriptedTool:
    """Fails a scripted number of times per action, then succeeds.

    Use -1 as the count to fail forever. name="browser" lets tests exercise
    the existing browser-phase retry classification.
    """

    name = "browser"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self, failures, on_fail=None):
        self.failures = dict(failures)
        self.on_fail = on_fail
        self.calls = []

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def execute(self, plan, approved=False):
        self.calls.append(plan.action)
        remaining = self.failures.get(plan.action, 0)
        if remaining != 0:
            if remaining > 0:
                self.failures[plan.action] = remaining - 1
            if self.on_fail is not None:
                self.on_fail()
            return ToolResult(status="failed", message="transient read-only failure")
        return ToolResult(status="completed", output={"action": plan.action})


def browser_step(action, phase="open", risk="low"):
    return PlanStep(tool="browser", action=action, risk=risk, parameters={"phase": phase})


def loop_for(steps, tool=None):
    registry = ToolRegistry()
    registry.register(tool or ScriptedTool({}))
    return AgentLoop(FakeAgent(steps), registry)


def recovery_observations(state):
    return [item for item in state.observations if item.summary == "reobserve_for_recovery"]


# --- budgets ----------------------------------------------------------------


def test_retry_budget_resets_between_steps():
    tool = ScriptedTool({"open page": 2, "fill form": 2})
    steps = [browser_step("open page", "open"), browser_step("fill form", "fill")]
    state = loop_for(steps, tool).run("two steps", [])
    assert state.status == "completed"
    # Each step consumed its own fresh budget of 2 retries (a shared budget
    # would run out during step two and fail the run).
    assert tool.calls == ["open page"] * 3 + ["fill form"] * 3
    assert len(recovery_observations(state)) == 4


def test_idempotent_failure_retries_at_most_twice():
    tool = ScriptedTool({"open page": -1})
    state = loop_for([browser_step("open page", "open")], tool).run("doomed", [])
    assert state.status == "failed"
    assert state.error == "transient read-only failure"
    assert tool.calls == ["open page"] * (1 + IDEMPOTENT_STEP_RETRIES)
    assert len(recovery_observations(state)) == IDEMPOTENT_STEP_RETRIES


def test_mutating_failure_gets_zero_automatic_retries():
    tool = ScriptedTool({"submit form": -1})
    state = loop_for([browser_step("submit form", "submit")], tool).run("mutating", [])
    assert state.status == "failed"
    assert tool.calls == ["submit form"]  # mutating phase: no retry at all
    assert recovery_observations(state) == []


def test_high_risk_failure_gets_zero_automatic_retries():
    tool = ScriptedTool({"verify page": -1})
    state = loop_for([browser_step("verify page", "verify", risk="high")], tool).run("high", [], gate=lambda _i, _s: None)
    assert state.status == "failed"
    assert tool.calls == ["verify page"]  # risk=high is never auto-retried
    assert recovery_observations(state) == []


def test_run_global_recovery_cap_is_enforced():
    names = ("one", "two", "three", "four")
    tool = ScriptedTool({name: 2 for name in names})
    steps = [browser_step(name, "open") for name in names]
    state = loop_for(steps, tool).run("global cap", [])
    assert state.status == "failed"
    # The run-global cap stopped recovery during step three.
    assert len(recovery_observations(state)) == RUN_RECOVERY_ATTEMPTS
    assert tool.calls == ["one"] * 3 + ["two"] * 3 + ["three"] * 2


def test_no_infinite_retry_loop_on_a_permanently_failing_step():
    tool = ScriptedTool({"open page": -1})
    steps = [browser_step("open page", "open"), browser_step("fill form", "fill"), browser_step("submit form", "submit")]
    state = loop_for(steps, tool).run("doomed multi-step", [])
    assert state.status == "failed"
    assert tool.calls == ["open page"] * (1 + IDEMPOTENT_STEP_RETRIES)
    assert [item["action"] for item in state.tool_history] == ["open page"]
    assert state.error == "transient read-only failure"


def test_successful_steps_advance_normally_without_spurious_retries():
    tool = ScriptedTool({})
    steps = [browser_step("open page", "open"), browser_step("fill form", "fill"), browser_step("verify page", "verify")]
    state = loop_for(steps, tool).run("happy path", [])
    assert state.status == "completed"
    assert tool.calls == ["open page", "fill form", "verify page"]
    assert [item["status"] for item in state.tool_history] == ["completed", "completed", "completed"]
    assert recovery_observations(state) == []


# --- stop behaviour ---------------------------------------------------------


def test_stop_before_run_executes_nothing():
    tool = ScriptedTool({})
    stop = Event()
    stop.set()
    state = loop_for([browser_step("open page", "open")], tool).run("stopped", [], stop_event=stop)
    assert state.status == "stopped"
    assert tool.calls == []


def test_stop_during_retry_halts_recovery_immediately():
    stop = Event()
    tool = ScriptedTool({"open page": -1}, on_fail=stop.set)
    state = loop_for([browser_step("open page", "open")], tool).run("stopped mid-retry", [], stop_event=stop)
    assert tool.calls == ["open page"]  # no retry once the stop event is set
    assert recovery_observations(state) == []


# --- destructive actions ----------------------------------------------------


def test_failed_destructive_delete_never_retries(tmp_path):
    tool = DesktopTool(tmp_path)
    registry = ToolRegistry()
    registry.register(tool)
    delete_step = tool.plan(AgentRequest(request="delete the requested file"))[0]
    assert delete_step.risk == "high"

    calls = []
    original = tool.execute

    def counting_execute(plan, approved=False):
        calls.append(plan.action)
        return original(plan, approved)

    tool.execute = counting_execute
    state = AgentLoop(FakeAgent([delete_step]), registry).run("delete", [], gate=lambda _i, _s: None)
    assert state.status == "failed"
    assert state.error == "Delete file is not yet supported."
    assert len(calls) == 1  # failed destructive action: exactly one attempt


# --- classification ---------------------------------------------------------


def test_idempotent_classification_uses_existing_action_tool_risk_data():
    assert is_idempotent_step(browser_step("open", "open")) is True
    assert is_idempotent_step(browser_step("fill", "fill")) is True
    assert is_idempotent_step(browser_step("verify", "verify")) is True
    assert is_idempotent_step(browser_step("observe", "")) is True
    assert is_idempotent_step(browser_step("submit", "submit")) is False
    assert is_idempotent_step(browser_step("verify", "verify", risk="high")) is False

    research = PlanStep(tool="web_research", action="search")
    assert is_idempotent_step(research) is True
    gmail = PlanStep(tool="gmail", action="prepare email draft", risk="high")
    assert is_idempotent_step(gmail) is False
    unknown = PlanStep(tool="unknown_tool", action="do things")
    assert is_idempotent_step(unknown) is False

    desktop_wait = PlanStep(tool="desktop", action="wait", parameters={"action": {"type": "wait"}})
    desktop_shot = PlanStep(tool="desktop", action="screenshot", parameters={"action": {"type": "take_screenshot"}})
    desktop_click = PlanStep(tool="desktop", action="click", parameters={"action": {"type": "click"}})
    desktop_no_action = PlanStep(tool="desktop", action="mystery")
    assert is_idempotent_step(desktop_wait) is True
    assert is_idempotent_step(desktop_shot) is True
    assert is_idempotent_step(desktop_click) is False
    assert is_idempotent_step(desktop_no_action) is False


def test_budget_defaults_are_the_specified_bounds():
    assert IDEMPOTENT_STEP_RETRIES == 2
    assert RUN_RECOVERY_ATTEMPTS == 5
