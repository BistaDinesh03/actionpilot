from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ComputerAction(BaseModel):
    environment: Literal["browser", "desktop"]
    action: str
    target: dict[str, Any] = Field(default_factory=dict)
    value: str | None = None
    risk: Literal["low", "medium", "high"] = "low"

    @model_validator(mode="after")
    def validate_action(self) -> "ComputerAction":
        allowed = {"navigate", "click", "type", "select", "scroll", "press", "read", "launch_application", "focus_window", "type_text", "press_key", "hotkey", "screenshot"}
        if self.action not in allowed:
            raise ValueError("Unsupported computer action")
        return self
