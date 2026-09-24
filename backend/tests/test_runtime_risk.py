"""Runtime risk safety (Milestone F).

Immediately before every actual action the loop re-classifies risk from
existing step metadata plus the current bounded observation. Producer-high
is never de-escalated, the existing HIGH_WORDS are re-checked (no second
risk system), and any escalation runs through the exact same approval gate
as a producer-high step.
"""

from app.services.agent.loop import AgentLoop
from app.services.agent.models import AgentPlan, PlanStep, ToolResult
from app.services.agent.planner import runtime_risk
from app.services.agent.registry import ToolRegistry
from app.services.agent.state import Observation

from app.services.desktop.safety import HIGH_WORDS


# --- helpers -----------------------------------------------------------------


class FakeAgent:
    def __init__(self, steps):
        self.steps = steps

    def plan(self, request, skills):
        return AgentPlan(request=request.request, intent="test", confidence=1, steps=self.steps)


def low_step(action="Open the local account demo page", risk="low", tool="browser"):
    return PlanStep(tool=tool, action=action, risk=risk, parameters={"phase": "open"})


def control(name):
    return {"tag": "button", "role": "button", "id": None, "name": name, "visible": True}


def observation_with(elements, available=True):
    return Observation(kind="browser", summary="page", data={"available": available, "elements": elements, "elements_total": len(elements), "elements_truncated": False})


class ObservingTool:
    name = "browser"
    description = "test"
    capabilities = []
    risk_level = "low"

    def __init__(self, elements=None, available=True):
        self.elements = elements or []
        self.available = available
        self.execute_calls = 0

    def can_handle(self, request):
        return True

    def plan(self, request):
        return []

    def observe(self, plan):
        return observation_with(self.elements, available=self.available)

    def execute(self, plan, approved=False):
        self.execute_calls += 1
        return ToolResult(status="completed", output={"action": plan.action})


def loop_for(tool, step):
    registry = ToolRegistry()
    registry.register(tool)
    return AgentLoop(FakeAgent([step]), registry)


# --- unit: classification -----------------------------------------------------


def test_producer_high_risk_is_never_de_escalated():
    high = low_step(action="Open the page", risk="high")
    assert runtime_risk(high, None) == "high"
    assert runtime_risk(high, observation_with([control("Submit")])) == "high"
    assert runtime_risk(high, observation_with([])) == "high"


def test_action_text_reuses_the_existing_high_words():
    for word in HIGH_WORDS:
        step = low_step(action=f"Perform {word} on the target", risk="low")
        assert runtime_risk(step, None) == "high", word
    assert runtime_risk(low_step(action="Delete the requested file"), None) == "high"
    assert runtime_risk(low_step(action="Fill the account form"), None) == "low"


def test_fresh_observation_controls_can_escalate_risk():
    step = low_step()
    assert runtime_risk(step, observation_with([control("Delete account")])) == "high"
    assert runtime_risk(step, observation_with([control("Submit"), control("Full name")])) == "low"


def test_runtime_risk_passes_through_producer_levels():
    assert runtime_risk(low_step(risk="low"), None) == "low"
    assert runtime_risk(low_step(risk="medium"), observation_with([control("Submit")])) == "medium"
    # An escalation always outranks a medium producer level.
    assert runtime_risk(low_step(risk="medium"), observation_with([control("Publish post")])) == "high"


def test_unavailable_observations_do_not_influence_risk():
    step = low_step()
    assert runtime_risk(step, observation_with([], available=False)) == "low"
    assert runtime_risk(step, observation_with([{"name": None}], available=False)) == "low"


# --- loop: escalations gate exactly like producer-high ------------------------


def test_escalated_risk_gates_before_any_execution():
    tool = ObservingTool(elements=[control("Delete account")])
    events = []
    state = loop_for(tool, low_step()).run("escalated", [], progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "waiting_confirmation"
    assert tool.execute_calls == 0  # nothing executed before the gate
    summaries = [item.summary for item in state.observations]
    assert "runtime_risk" in summaries
    assert "approval_required" in summaries
    escalation = next(item for item in state.observations if item.summary == "runtime_risk")
    assert escalation.data["producer"] == "low"
    assert escalation.data["runtime"] == "high"
    assert escalation.data["step_index"] == 0
    # Without a gate the run waits on approval_required (pre-existing behaviour).
    assert not any(event == "step_started" for event, _i, _d in events)


def test_escalated_risk_runs_when_the_gate_approves():
    tool = ObservingTool(elements=[control("Delete account")])
    state = loop_for(tool, low_step()).run("approved", [], gate=lambda _i, _s: None)
    assert state.status == "completed"
    assert tool.execute_calls == 1
    summaries = [item.summary for item in state.observations]
    assert "runtime_risk" in summaries
    assert "approval_granted" in summaries


def test_escalated_risk_stops_when_the_gate_rejects():
    tool = ObservingTool(elements=[control("Delete account")])
    state = loop_for(tool, low_step()).run("rejected", [], gate=lambda _i, _s: "operator rejected the escalation")
    assert state.status == "stopped"
    assert state.error == "operator rejected the escalation"
    assert tool.execute_calls == 0
    summaries = [item.summary for item in state.observations]
    assert "approval_rejected" in summaries


def test_action_text_escalation_also_gates_before_execution():
    tool = ObservingTool()  # no observation needed: the planned action says it
    state = loop_for(tool, low_step(action="Delete the requested file")).run("text escalation", [])
    assert state.status == "waiting_confirmation"
    assert tool.execute_calls == 0
    escalation = next(item for item in state.observations if item.summary == "runtime_risk")
    assert escalation.data["producer"] == "low"
    assert escalation.data["runtime"] == "high"


# --- loop: benign steps keep their existing behaviour -------------------------


def test_low_risk_steps_never_trigger_the_gate():
    tool = ObservingTool(elements=[control("Submit"), control("Full name")])
    events = []
    state = loop_for(tool, low_step()).run("benign", [], progress=lambda e, i, d: events.append((e, i, d)))
    assert state.status == "completed"
    assert tool.execute_calls == 1
    # No escalation was recorded and no approval machinery engaged.
    assert [item.summary for item in state.observations if item.summary in {"runtime_risk", "approval_required"}] == []
    names = [event for event, _i, _d in events]
    assert "waiting_approval" not in names
    assert names == ["observe", "step_started", "step_completed"]


def test_tool_without_observations_keeps_producer_risk():
    class PlainTool:
        name = "browser"
        description = "test"
        capabilities = []
        risk_level = "low"

        def __init__(self):
            self.execute_calls = 0

        def can_handle(self, request):
            return True

        def plan(self, request):
            return []

        def execute(self, plan, approved=False):
            self.execute_calls += 1
            return ToolResult(status="completed", output={})

    tool = PlainTool()
    state = loop_for(tool, low_step()).run("plain", [], gate=lambda _i, _s: (_ for _ in ()).throw(AssertionError("gate must not run for low risk")))
    assert state.status == "completed"
    assert tool.execute_calls == 1
