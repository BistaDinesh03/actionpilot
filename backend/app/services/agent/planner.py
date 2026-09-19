from __future__ import annotations

from .models import AgentPlan


def calculate_risk(plan: AgentPlan) -> AgentPlan:
    plan.requires_confirmation = any(step.risk == "high" for step in plan.steps)
    return plan
