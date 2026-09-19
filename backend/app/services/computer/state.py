from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ComputerActionState(BaseModel):
    action: str
    environment: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


class ComputerTaskState(BaseModel):
    goal: str
    environment: str | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[ComputerActionState] = Field(default_factory=list)
    status: Literal["running", "paused", "stopped", "completed", "failed"] = "running"
