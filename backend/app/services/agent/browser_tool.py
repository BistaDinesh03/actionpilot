from __future__ import annotations

from typing import Any

from playwright.sync_api import sync_playwright

from .models import AgentRequest, PlanStep, ToolResult
from .observer import observe_page
from ..computer.observation import from_browser


class BrowserTool:
    name = "browser"
    description = "Safely browse public pages and return bounded visible observations."
    capabilities = ["open URL", "search", "click", "type", "press", "scroll", "read page", "open links", "screenshot"]
    risk_level = "low"

    def can_handle(self, request: AgentRequest) -> bool:
        return True

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        return [PlanStep(tool=self.name, action="open and observe public page", risk="low", parameters={"request": request.request, "url": request.variables.get("url")})]

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        url = plan.parameters.get("url")
        if not url:
            return ToolResult(status="completed", output={"message": "No URL was supplied for browser observation."})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(str(url), wait_until="domcontentloaded", timeout=20_000)
                observation = observe_page(page)
                browser.close()
            raw = observation.model_dump()
            return ToolResult(status="completed", output={**raw, "observation": from_browser(raw).model_dump()})
        except Exception:
            return ToolResult(status="failed", message="Browser observation failed safely.")
