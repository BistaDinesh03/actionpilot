from __future__ import annotations

from typing import Any, Protocol

from .models import AgentRequest, PlanStep, ToolResult


class Tool(Protocol):
    name: str
    description: str
    capabilities: list[str]
    risk_level: str

    def can_handle(self, request: AgentRequest) -> bool: ...
    def plan(self, request: AgentRequest) -> list[PlanStep]: ...
    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def descriptions(self) -> list[dict[str, Any]]:
        return [{"name": tool.name, "description": tool.description, "capabilities": tool.capabilities, "risk_level": tool.risk_level} for tool in self._tools.values()]


def build_default_registry(skill_matcher: Any, gmail_service: Any, runtime_dir: Any = None, browser_runtime_dir: Any = None) -> ToolRegistry:
    from .agent import GmailTool, SkillTool, WebResearchTool
    from .browser_tool import BrowserTool
    from ..desktop.tool import DesktopTool

    registry = ToolRegistry()
    registry.register(SkillTool(skill_matcher))
    registry.register(GmailTool(gmail_service))
    registry.register(WebResearchTool())
    # Agent browser sessions keep their screenshots under runtime/agent/ so the
    # step-screenshot endpoint can serve them through contained_runtime_path();
    # the %TEMP% default would be rejected by that containment check.
    registry.register(BrowserTool(browser_runtime_dir))
    registry.register(DesktopTool(runtime_dir))
    return registry
