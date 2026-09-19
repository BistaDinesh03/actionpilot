from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.services.agent.agent import ActionPilotAgent
from app.services.agent.models import AgentPlan, AgentRequest
from app.services.agent.models import ToolResult
from app.services.agent.registry import build_default_registry
from app.services.agent.router import AgentRouter
from app.services.matching.matcher import match_command


@pytest.fixture
def agent():
    registry = build_default_registry(match_command, object())
    return ActionPilotAgent(registry, AgentRouter(registry))


def saved_skill():
    return {"id": "keyboard", "name": "Demo Keyboard Search", "description": "Search the demo shop", "domains": ["127.0.0.1:4173"], "steps": [{"type": "type", "label": "Search", "value": "keyboard"}]}


def test_registry_contains_initial_tools(agent):
    names = {tool["name"] for tool in agent.registry.descriptions()}
    assert names == {"skill", "gmail", "web_research", "browser", "desktop"}


def test_skill_gmail_and_research_routing(agent):
    skill_plan = agent.plan(AgentRequest(request="Run my keyboard workflow"), [saved_skill()])
    gmail_plan = agent.plan(AgentRequest(request="Email John that I will be late"), [saved_skill()])
    research_plan = agent.plan(AgentRequest(request="Research recent AI automation posts"), [saved_skill()])
    assert skill_plan.intent == "run_skill"
    assert skill_plan.steps[0].tool == "skill"
    assert gmail_plan.intent == "email"
    assert gmail_plan.requires_confirmation is True
    assert research_plan.intent == "web_research"
    assert research_plan.steps[0].tool == "web_research"


def test_desktop_routing(agent):
    plan = agent.plan(AgentRequest(request="Open Notepad and write hello"), [saved_skill()])
    assert plan.intent == "desktop"
    assert plan.steps[0].tool == "desktop"


def test_mixed_plan_research_then_gmail(agent):
    plan = agent.plan(AgentRequest(request="Research AI automation and email John the summary"), [saved_skill()])
    assert plan.intent == "research_and_email"
    assert [step.tool for step in plan.steps] == ["web_research", "gmail"]
    assert plan.requires_confirmation is True


def test_unknown_request_and_no_ai_key_are_deterministic(agent):
    plan = agent.plan(AgentRequest(request="Do something mysterious"), [])
    assert plan.intent == "clarify"
    assert plan.steps == []


def test_malformed_agent_plan_is_rejected():
    with pytest.raises(ValidationError):
        AgentPlan.model_validate({"request": "x", "intent": "run_shell", "confidence": 2, "steps": []})


def test_agent_plan_endpoint_and_high_risk_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "agent.db")
    main.init_db()
    monkeypatch.setattr(main.agent_registry.get("web_research"), "execute", lambda plan, approved=False: ToolResult(status="completed", output={"sources": [], "ideas": []}))
    with TestClient(main.app) as client:
        plan = client.post("/api/agent/plan", json={"request": "Research recent AI automation posts and email John the summary"})
        assert plan.status_code == 200
        body = plan.json()
        assert body["steps"][0]["tool"] == "web_research"
        assert body["requires_confirmation"] is True
        blocked = client.post("/api/agent/execute", json={"plan": body, "approved": False})
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "waiting_confirmation"
        assert blocked.json()["requires_confirmation"] is True
