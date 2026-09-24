from __future__ import annotations

from typing import Any

from ..desktop.safety import HIGH_WORDS
from .models import AgentPlan, PlanStep


def calculate_risk(plan: AgentPlan) -> AgentPlan:
    plan.requires_confirmation = any(step.risk == "high" for step in plan.steps)
    return plan


def runtime_risk(step: PlanStep, observation: Any | None = None) -> str:
    """Classify risk immediately before an action executes.

    Extends the existing risk data instead of creating a second system:
    producer-high is never de-escalated, and the same deterministic
    HIGH_WORDS the desktop safety module uses are re-checked against the
    planned action text and the fresh bounded observation's visible
    controls. When nothing new is detected, the step's own risk level
    stands.
    """
    if step.risk == "high":
        return "high"  # producer-high is never de-escalated
    if any(word in step.action.lower() for word in HIGH_WORDS):
        return "high"
    data = observation.data if observation is not None and getattr(observation, "data", None) is not None else None
    if isinstance(data, dict):
        for element in data.get("elements") or []:
            name = str(element.get("name") or "").lower()
            if any(word in name for word in HIGH_WORDS):
                return "high"
    if step.risk == "medium":
        return "medium"
    return str(step.risk)
