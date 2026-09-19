from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Observation(BaseModel):
    kind: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    task_id: str
    goal: str
    current_step: int = 0
    plan: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    status: Literal["queued", "running", "waiting_confirmation", "completed", "failed", "paused", "stopped"] = "queued"
    error: str | None = None
