from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]


class AgentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    variables: dict[str, str] = Field(default_factory=dict)


class PlanStep(BaseModel):
    tool: str
    action: str
    risk: RiskLevel = "low"
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    request: str
    intent: str
    confidence: float = Field(ge=0, le=1)
    steps: list[PlanStep]
    variables: dict[str, str] = Field(default_factory=dict)
    requires_confirmation: bool = False
    message: str | None = None


class ToolResult(BaseModel):
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    message: str | None = None
    next_steps: list[PlanStep] = Field(default_factory=list)
