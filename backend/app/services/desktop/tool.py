from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..agent.models import AgentRequest, PlanStep, ToolResult
from .actions import execute
from .models import DesktopAction
from .safety import requires_confirmation
from ..computer.observation import from_desktop


class DesktopTool:
    name = "desktop"
    description = "Interact with allowlisted Windows applications through UI Automation."
    capabilities = ["launch application", "focus window", "semantic click", "type text", "hotkey", "screenshot"]
    risk_level = "medium"

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir

    def can_handle(self, request: AgentRequest) -> bool:
        return bool(re.search(r"\b(open|launch|type|write|screenshot|desktop|notepad|vs code|visual studio code)\b", request.request, re.IGNORECASE))

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        text = request.request.lower()
        application = "notepad" if "notepad" in text else "vscode" if "vs code" in text or "visual studio code" in text else "chrome" if "chrome" in text else None
        steps: list[PlanStep] = []
        if application:
            steps.append(PlanStep(tool=self.name, action=f"Open {application}", risk="low", parameters={"action": {"type": "launch_application", "application_id": application}}))
        if "screenshot" in text:
            steps.append(PlanStep(tool=self.name, action="Take desktop screenshot", risk="low", parameters={"action": {"type": "take_screenshot"}}))
        match = re.search(r"(?:write|type)\s+(.+)$", request.request, re.IGNORECASE)
        if match:
            steps.append(PlanStep(tool=self.name, action="Type text into the focused application", risk="low", parameters={"action": {"type": "type_text", "value": match.group(1).strip().rstrip(".")}}))
        if "delete" in text:
            steps.append(PlanStep(tool=self.name, action="Delete the requested file", risk="high", parameters={"action": {"type": "wait", "value": "0", "risk": "high"}}))
        return steps

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        action = DesktopAction.model_validate(plan.parameters.get("action", {}))
        if requires_confirmation(action) and not approved:
            return ToolResult(status="waiting_confirmation", requires_confirmation=True, message="Confirmation required before this desktop action.")
        try:
            observation = execute(action, self.runtime_dir)
            raw = observation.model_dump()
            return ToolResult(status="completed", output={**raw, "observation": from_desktop(raw).model_dump()})
        except (ValueError, LookupError, FileNotFoundError, PermissionError) as error:
            return ToolResult(status="failed", message=str(error))
        except Exception:
            return ToolResult(status="failed", message="Desktop action could not complete safely.")
