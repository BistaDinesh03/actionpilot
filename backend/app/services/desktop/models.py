from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DesktopTarget(BaseModel):
    name: str | None = None
    control_type: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    coordinates: tuple[int, int] | None = None


class DesktopAction(BaseModel):
    type: Literal["launch_application", "focus_window", "click", "double_click", "type_text", "press_key", "hotkey", "scroll", "wait", "take_screenshot"]
    target: DesktopTarget | None = None
    application_id: str | None = None
    value: str | None = None
    risk: Literal["low", "medium", "high"] = "low"


class DesktopObservation(BaseModel):
    active_window: str | None = None
    windows: list[dict[str, Any]] = Field(default_factory=list)
    controls: list[dict[str, Any]] = Field(default_factory=list)
    screen_size: dict[str, int] = Field(default_factory=dict)
    screenshot: str | None = None
