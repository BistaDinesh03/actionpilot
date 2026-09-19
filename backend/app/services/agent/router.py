from __future__ import annotations

import re
from typing import Any

from ..gmail.service import parse_email_command
from ..matching.matcher import match_command
from .models import AgentPlan, AgentRequest, PlanStep
from .registry import ToolRegistry


class AgentRouter:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def plan(self, request: AgentRequest, skills: list[dict[str, Any]]) -> AgentPlan:
        text = request.request.strip()
        lowered = text.lower()
        research = bool(re.search(r"\b(research|find recent|search the web|compare|posts about|under [¥$€£]?\s?\d)\b", lowered))
        email = parse_email_command(text) is not None or bool(re.search(r"\b(email|reply to)\b", lowered))
        desktop = bool(re.search(r"\b(open|launch|notepad|vs code|visual studio code|desktop screenshot|type into)\b", lowered))
        if desktop and not research and not email:
            return AgentPlan(request=text, intent="desktop", confidence=0.94, variables=request.variables, steps=self.registry.get("desktop").plan(request))
        if research and email:
            return AgentPlan(request=text, intent="research_and_email", confidence=0.92, variables=request.variables, steps=[PlanStep(tool="web_research", action="research and summarize public sources", risk="low", parameters={"query": text}), PlanStep(tool="gmail", action="prepare email draft from research", risk="high", parameters={"request": text})], requires_confirmation=True)
        if research:
            return AgentPlan(request=text, intent="web_research", confidence=0.9, variables=request.variables, steps=self.registry.get("web_research").plan(request))
        if email:
            return AgentPlan(request=text, intent="email", confidence=0.9, variables=request.variables, steps=self.registry.get("gmail").plan(request), requires_confirmation=True)
        matched = match_command(text, skills)
        if matched.get("matched"):
            variables = {**matched.get("variables", {}), **request.variables}
            steps = self.registry.get("skill").plan(AgentRequest(request=text, variables=variables))
            steps[0].parameters.update({"skill_id": matched["skill_id"], "variables": variables})
            steps[0].risk = "high" if matched.get("requires_confirmation") else "low"
            return AgentPlan(request=text, intent="run_skill", confidence=matched["confidence"], variables=variables, steps=steps, requires_confirmation=matched.get("requires_confirmation", False))
        return AgentPlan(request=text, intent="clarify", confidence=matched.get("confidence", 0), variables={}, steps=[], message=matched.get("message", "I could not determine which tool should handle this request."))
