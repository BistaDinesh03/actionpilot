from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ComputerObservation(BaseModel):
    environment: Literal["browser", "desktop"]
    active_window: str | None = None
    url: str | None = None
    title: str | None = None
    visible_text: str = ""
    controls: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    buttons: list[Any] = Field(default_factory=list)
    screenshot_path: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def from_browser(data: dict[str, Any]) -> ComputerObservation:
    return ComputerObservation(environment="browser", active_window=data.get("title"), url=data.get("url"), title=data.get("title"), visible_text=data.get("visible_text", ""), controls=data.get("forms", []), links=data.get("links", []), buttons=data.get("buttons", []), screenshot_path=data.get("screenshot"))


def from_desktop(data: dict[str, Any]) -> ComputerObservation:
    return ComputerObservation(environment="desktop", active_window=data.get("active_window"), title=data.get("active_window"), controls=data.get("controls", []), screenshot_path=data.get("screenshot"), buttons=[])
