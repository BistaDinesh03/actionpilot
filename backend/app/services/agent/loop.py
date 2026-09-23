from __future__ import annotations

import uuid
from threading import Event
from typing import Any

from ..execution.models import ApprovalGate, ProgressCallback
from .models import AgentPlan, AgentRequest, PlanStep, ToolResult
from .observer import observe_result
from .state import AgentState


class AgentLoop:
    def __init__(self, agent: Any, registry: Any, max_steps: int = 15, max_recovery_attempts: int = 3) -> None:
        self.agent = agent
        self.registry = registry
        self.max_steps = max_steps
        self.max_recovery_attempts = max_recovery_attempts

    def run(self, request: str, skills: list[dict[str, Any]], variables: dict[str, str] | None = None, stop_event: Event | None = None, pause_event: Event | None = None, gate: ApprovalGate | None = None, progress: ProgressCallback | None = None) -> AgentState:
        plan: AgentPlan = self.agent.plan(AgentRequest(request=request, variables=variables or {}), skills)
        state = AgentState(task_id=str(uuid.uuid4()), goal=request, plan=[step.model_dump() for step in plan.steps], variables=plan.variables, status="running")
        stop_event = stop_event or Event()
        pause_event = pause_event or Event()
        steps = list(plan.steps)
        index = 0
        recovery_attempts = 0

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
            approved = False
            if step.risk == "high":
                if gate is None:
                    state.status = "waiting_confirmation"
                    state.observations.append(observe_result("approval_required", {"message": "Explicit approval is required before risky actions.", "action": step.action}))
                    break
                notify("waiting_approval", index, {"step": {"label": step.action, "type": step.tool}})
                reason = gate(index, step.model_dump())
                if reason:
                    state.status = "stopped"
                    state.error = reason
                    state.observations.append(observe_result("approval_rejected", {"reason": reason, "action": step.action}))
                    break
                approved = True
                state.observations.append(observe_result("approval_granted", {"action": step.action}))
            notify("step_started", index, {"step": {"label": step.action, "type": step.tool}})
            tool = self.registry.get(step.tool)
            result: ToolResult = tool.execute(step, approved=approved)
            while result.status == "failed" and recovery_attempts < self.max_recovery_attempts and not stop_event.is_set():
                recovery_attempts += 1
                state.observations.append(observe_result("reobserve_for_recovery", {"attempt": recovery_attempts, "error": result.message}))
                result = tool.execute(step, approved=approved)
            state.tool_history.append({"tool": step.tool, "action": step.action, "status": result.status})
            state.observations.append(observe_result(result.status, result.output))
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
