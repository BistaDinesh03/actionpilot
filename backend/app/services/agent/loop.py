from __future__ import annotations

import uuid
from threading import Event
from typing import Any

from ..execution.models import ApprovalGate, ProgressCallback
from .models import AgentPlan, AgentRequest, PlanStep, ToolResult
from .observer import observe_result
from .planner import runtime_risk
from .recovery import classify_recovery
from .state import AgentState

# Bounded recovery budgets. Each step gets a fresh per-step budget, the whole
# run shares a hard global cap, and mutating/destructive steps never retry
# automatically. Together these guarantee no run can loop forever.
IDEMPOTENT_STEP_RETRIES = 2
RUN_RECOVERY_ATTEMPTS = 5

_MUTATING_TOOLS = frozenset({"gmail", "skill"})
_IDEMPOTENT_BROWSER_PHASES = frozenset({"open", "fill", "verify"})
_MUTATING_BROWSER_PHASES = frozenset({"submit"})
_IDEMPOTENT_DESKTOP_TYPES = frozenset({"wait", "take_screenshot", "focus_window"})


def is_idempotent_step(step: PlanStep) -> bool:
    """Deterministic retry classification from existing action/tool/risk data.

    Read-only or idempotent steps may be retried (bounded). Mutating steps,
    destructive (high-risk) steps, and anything that cannot be classified
    from existing metadata never retry automatically.
    """
    if step.risk == "high":
        return False
    if step.tool in _MUTATING_TOOLS:
        return False
    if step.tool == "web_research":
        return True  # read-only browsing and summarising
    if step.tool == "browser":
        phase = str(step.parameters.get("phase") or "")
        if not phase:
            return True  # plain page observation: read-only
        if phase in _MUTATING_BROWSER_PHASES:
            return False
        return phase in _IDEMPOTENT_BROWSER_PHASES
    if step.tool == "desktop":
        action = step.parameters.get("action")
        action_type = action.get("type") if isinstance(action, dict) else None
        return action_type in _IDEMPOTENT_DESKTOP_TYPES
    return False  # unknown tool: conservative, no automatic retry


class AgentLoop:
    def __init__(self, agent: Any, registry: Any, max_steps: int = 15, max_recovery_attempts: int = IDEMPOTENT_STEP_RETRIES, max_run_recovery_attempts: int = RUN_RECOVERY_ATTEMPTS) -> None:
        self.agent = agent
        self.registry = registry
        self.max_steps = max_steps
        self.max_recovery_attempts = max_recovery_attempts
        self.max_run_recovery_attempts = max_run_recovery_attempts

    def run(self, request: str, skills: list[dict[str, Any]], variables: dict[str, str] | None = None, stop_event: Event | None = None, pause_event: Event | None = None, gate: ApprovalGate | None = None, progress: ProgressCallback | None = None) -> AgentState:
        plan: AgentPlan = self.agent.plan(AgentRequest(request=request, variables=variables or {}), skills)
        state = AgentState(task_id=str(uuid.uuid4()), goal=request, plan=[step.model_dump() for step in plan.steps], variables=plan.variables, status="running")
        stop_event = stop_event or Event()
        pause_event = pause_event or Event()
        steps = list(plan.steps)
        index = 0
        run_recovery = 0  # run-global recovery budget (shared across steps)

        def notify(event: str, step_index: int, data: dict[str, Any]) -> None:
            if progress is not None:
                progress(event, step_index, data)

        while index < len(steps) and index < self.max_steps:
            if stop_event.is_set():
                state.status = "stopped"
                break
            while pause_event.is_set() and not stop_event.is_set():
                stop_event.wait(0.05)
            if stop_event.is_set():
                state.status = "stopped"
                break
            state.current_step = index + 1
            step_data = steps[index]
            step = PlanStep.model_validate(step_data)
            state.observations.append(observe_result("planning_next_step", {"tool": step.tool, "action": step.action}))
            tool = self.registry.get(step.tool)
            # Observe the live environment before any action (bounded, read-only).
            # A terminal run never observes again, and a failed observation is
            # skipped honestly rather than fabricated.
            observation = None
            observe = getattr(tool, "observe", None)
            if callable(observe) and state.status == "running":
                try:
                    observation = observe(step)
                except Exception:
                    observation = None
                if observation is not None:
                    state.observations.append(observe_result("action_observation", {**observation.data, "step_index": index}))
                    notify("observe", index, {"summary": observation.summary, "step_index": index, "step": {"label": step.action, "type": step.tool}})
            # Decide, using only the fresh bounded observation. An exception
            # here falls back to the original plan rather than guessing.
            adapted_step = step
            decision = None
            adapt = getattr(tool, "adapt", None)
            if observation is not None and callable(adapt):
                try:
                    adapted_step, decision = adapt(step, observation)
                except Exception:
                    adapted_step, decision = step, None
                if decision is not None:
                    state.observations.append(observe_result("decision", {"step_index": index, "kind": decision.kind, "reason": decision.reason, "replans": decision.replans, "target": decision.target}))
                    notify("decide", index, {"kind": decision.kind, "reason": decision.reason, "step_index": index, "step": {"label": step.action, "type": step.tool}})
            approved = False
            result: ToolResult | None = None
            if decision is not None and decision.kind == "fail":
                # Honest bounded failure: never act on a target that could not
                # be identified safely from the fresh observation.
                result = ToolResult(status="failed", message=decision.reason)
            else:
                # Runtime risk safety: re-classify immediately before acting,
                # from existing metadata plus the fresh observation. High risk
                # is never de-escalated, and an escalation runs through the
                # exact same approval gate as a producer-high step.
                risk = runtime_risk(adapted_step, observation)
                if risk != step.risk:
                    state.observations.append(observe_result("runtime_risk", {"step_index": index, "action": step.action, "producer": step.risk, "runtime": risk}))
                if risk == "high":
                    if gate is None:
                        state.status = "waiting_confirmation"
                        state.observations.append(observe_result("approval_required", {"message": "Explicit approval is required before risky actions.", "action": step.action}))
                        break
                    notify("waiting_approval", index, {"step": {"label": step.action, "type": step.tool}})
                    reason = gate(index, adapted_step.model_dump())
                    if reason:
                        state.status = "stopped"
                        state.error = reason
                        state.observations.append(observe_result("approval_rejected", {"reason": reason, "action": step.action}))
                        break
                    approved = True
                    state.observations.append(observe_result("approval_granted", {"action": step.action}))
                notify("step_started", index, {"step": {"label": step.action, "type": step.tool}})
                result = tool.execute(adapted_step, approved=approved)
                # Bounded, classified recovery: every decision is deterministic,
                # short, interruptible, and still counted against the hard
                # budgets, so no run can loop forever.
                step_recovery = 0
                step_budget = self.max_recovery_attempts if is_idempotent_step(adapted_step) else 0
                while result.status == "failed" and run_recovery < self.max_run_recovery_attempts and not stop_event.is_set():
                    decision = classify_recovery(
                        adapted_step,
                        result,
                        attempt=step_recovery,
                        budget=step_budget,
                        can_reobserve=callable(observe),
                        can_replan=callable(adapt),
                    )
                    state.observations.append(observe_result("recovery_decision", {"step_index": index, "kind": decision.kind, "reason": decision.reason, "attempt": step_recovery, "run_attempts": run_recovery, "delay": decision.delay}))
                    notify("recover", index, {"kind": decision.kind, "reason": decision.reason, "attempt": step_recovery, "run_attempts": run_recovery, "step_index": index, "step": {"label": step.action, "type": step.tool}})
                    if decision.kind == "stop":
                        break
                    if decision.kind == "ask":
                        # Hand the run to a human instead of retrying blindly.
                        result = ToolResult(status="waiting_confirmation", requires_confirmation=True, message=result.message, output=result.output)
                        break
                    if decision.delay > 0:
                        stop_event.wait(decision.delay)
                    if stop_event.is_set():
                        break
                    step_recovery += 1
                    run_recovery += 1
                    state.observations.append(observe_result("reobserve_for_recovery", {"attempt": step_recovery, "run_attempts": run_recovery, "error": result.message}))
                    if decision.kind in {"reobserve", "replan"} and callable(observe):
                        try:
                            fresh = observe(adapted_step)
                        except Exception:
                            fresh = None
                        if fresh is not None:
                            state.observations.append(observe_result("action_observation", {**fresh.data, "step_index": index}))
                            notify("observe", index, {"summary": fresh.summary, "step_index": index, "step": {"label": step.action, "type": step.tool}})
                            if decision.kind == "replan" and callable(adapt):
                                try:
                                    adapted_step, replan = adapt(step, fresh)
                                except Exception:
                                    replan = None
                                if replan is not None:
                                    state.observations.append(observe_result("decision", {"step_index": index, "kind": replan.kind, "reason": replan.reason, "replans": replan.replans, "target": replan.target}))
                                    notify("decide", index, {"kind": replan.kind, "reason": replan.reason, "step_index": index, "step": {"label": step.action, "type": step.tool}})
                    result = tool.execute(adapted_step, approved=approved)
            # Structured verification: a completed action that did not achieve
            # its intended outcome must fail honestly, never claim success.
            verification = result.output.get("verification") if isinstance(result.output, dict) else None
            if not isinstance(verification, dict):
                verification = None
            if verification is not None:
                notify("verify", index, {"passed": verification.get("passed") is True, "summary": verification.get("summary", ""), "step_index": index, "step": {"label": step.action, "type": step.tool}})
                if result.status == "completed" and verification.get("passed") is False:
                    summary = str(verification.get("summary") or "").strip()
                    result = ToolResult(status="failed", message=result.message or (f"Verification failed: {summary}" if summary else "Verification failed."), output=result.output)
            state.tool_history.append({"tool": step.tool, "action": step.action, "status": result.status})
            state.observations.append(observe_result(result.status, {**result.output, "step_index": index}))
            if result.next_steps:
                steps[index + 1:index + 1] = result.next_steps
                state.plan = [item.model_dump() if hasattr(item, "model_dump") else item for item in steps]
            if result.status in {"failed", "waiting_confirmation"}:
                state.status = "waiting_confirmation" if result.requires_confirmation else "failed"
                state.error = result.message
                notify("step_failed" if state.status == "failed" else "waiting_approval", index, {"error": result.message, "output": result.output, "step": {"label": step.action, "type": step.tool}})
                break
            notify("step_completed", index, {"status": result.status, "output": result.output, "step": {"label": step.action, "type": step.tool}})
            if result.output:
                state.result = {**(state.result or {}), **result.output}
            index += 1
        if index >= len(steps) and state.status == "running":
            state.status = "completed"
        if index >= self.max_steps and state.status == "running":
            state.status = "failed"
            state.error = "Maximum agent step count reached"
        return state
