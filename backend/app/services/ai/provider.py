from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class StructuredIntent(BaseModel):
    intent: str = Field(pattern=r"^(run_skill|clarify)$")
    skill_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    variables: dict[str, str] = Field(default_factory=dict)
    requires_confirmation: bool = False


class AIProvider(Protocol):
    def understand_command(self, command: str, skills: list[dict[str, Any]]) -> StructuredIntent: ...
    def extract_variables(self, command: str, skill: dict[str, Any]) -> dict[str, str]: ...
    def observe_screen(self, screenshot_path: str) -> dict[str, Any]: ...
    def identify_target(self, screenshot_path: str, description: str) -> dict[str, Any]: ...
    def verify_result(self, screenshot_path: str, expected: str) -> dict[str, Any]: ...
