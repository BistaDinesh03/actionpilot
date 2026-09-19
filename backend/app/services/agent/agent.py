from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

from ..gmail.models import EmailIntent
from ..gmail.service import GmailService, parse_email_command
from ..matching.matcher import match_command
from .models import AgentPlan, AgentRequest, PlanStep, ToolResult
from .registry import ToolRegistry


class SkillTool:
    name = "skill"
    description = "Run a saved browser Skill through the existing Playwright executor."
    capabilities = ["saved workflows", "browser automation"]
    risk_level = "low"

    def __init__(self, matcher: Any) -> None:
        self.matcher = matcher

    def can_handle(self, request: AgentRequest) -> bool:
        return bool(self.matcher(request.request, []))

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        return [PlanStep(tool=self.name, action="run saved Skill", risk="low", parameters={"request": request.request, "variables": request.variables})]

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        return ToolResult(status="delegated", output={"request": plan.parameters.get("request"), "variables": plan.parameters.get("variables", {})}, message="Skill execution is delegated to the existing run executor.")


class GmailTool:
    name = "gmail"
    description = "Prepare Gmail drafts and send only after explicit approval."
    capabilities = ["contact resolution", "drafts", "send", "replies"]
    risk_level = "high"

    def __init__(self, service: GmailService) -> None:
        self.service = service

    def can_handle(self, request: AgentRequest) -> bool:
        return parse_email_command(request.request) is not None or bool(re.search(r"\b(email|reply)\b", request.request, re.IGNORECASE))

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        intent = parse_email_command(request.request)
        action = "prepare email draft" if not intent or intent.intent == "send_email" else "prepare reply draft"
        return [PlanStep(tool=self.name, action=action, risk="high", parameters={"request": request.request})]

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        return ToolResult(status="waiting_confirmation", requires_confirmation=True, message="Gmail send requires explicit approval in the Gmail API flow.")


class WebResearchTool:
    name = "web_research"
    description = "Search public web pages, extract visible findings, and return cited sources."
    capabilities = ["web search", "source collection", "comparison", "content ideas"]
    risk_level = "low"

    def can_handle(self, request: AgentRequest) -> bool:
        return bool(re.search(r"\b(research|find recent|search the web|compare|posts about)\b", request.request, re.IGNORECASE))

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        return [PlanStep(tool=self.name, action="search public web", risk="low", parameters={"query": request.request}), PlanStep(tool=self.name, action="collect and compare visible sources", risk="low"), PlanStep(tool=self.name, action="summarize findings and generate ideas", risk="low")]

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        if not plan.parameters.get("query"):
            return ToolResult(status="completed", output={"step": plan.action})
        query = str(plan.parameters.get("query", ""))
        search_terms = re.sub(r"\b(find|recent|posts|about|give me|ideas|i could turn into content|research)\b", " ", query, flags=re.IGNORECASE).strip()
        search_url = f"https://www.bing.com/search?q={quote_plus(search_terms)}"
        sources: list[dict[str, str]] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
                links = page.locator("li.b_algo h2 a")
                if links.count() == 0:
                    links = page.locator("a.result__a")
                for index in range(min(5, links.count())):
                    link = links.nth(index)
                    title = link.inner_text().strip()
                    url = link.get_attribute("href") or ""
                    if not url:
                        continue
                    detail = browser.new_page()
                    try:
                        detail.goto(url, wait_until="domcontentloaded", timeout=15_000)
                        visible = detail.locator("body").inner_text(timeout=5_000)[:2_000]
                        sources.append({"title": title, "url": detail.url, "excerpt": visible})
                    except Exception:
                        sources.append({"title": title, "url": url, "excerpt": ""})
                    finally:
                        detail.close()
                browser.close()
        except Exception as error:
            return ToolResult(status="failed", message="Web research could not complete safely.", output={"error": str(error)[:240]})
        ideas = self._ideas(sources)
        return ToolResult(status="completed", output={"query": search_terms, "sources": sources, "ideas": ideas})

    @staticmethod
    def _ideas(sources: list[dict[str, str]]) -> list[str]:
        terms = Counter(word.lower() for source in sources for word in re.findall(r"[A-Za-z]{5,}", source.get("excerpt", "")))
        themes = [word for word, _count in terms.most_common(5)] or ["workflow", "automation", "results"]
        return [f"Explain how {theme} changes practical AI automation workflows." for theme in themes[:5]]


class ActionPilotAgent:
    def __init__(self, registry: ToolRegistry, router: Any) -> None:
        self.registry = registry
        self.router = router

    def plan(self, request: AgentRequest, skills: list[dict[str, Any]]) -> AgentPlan:
        return self.router.plan(request, skills)
