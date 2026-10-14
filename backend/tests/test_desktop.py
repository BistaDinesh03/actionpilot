import os
from pathlib import Path

import pytest

from app.services.agent.models import AgentRequest
from app.services.desktop.actions import PROCESSES
from app.services.desktop.models import DesktopAction
from app.services.desktop.safety import requires_confirmation
from app.services.desktop.tool import DesktopTool


def test_desktop_plan_and_allowlist(tmp_path):
    tool = DesktopTool(tmp_path)
    plan = tool.plan(AgentRequest(request="Open Notepad and write ActionPilot desktop test"))
    assert [step.parameters["action"]["type"] for step in plan] == ["launch_application", "type_text"]
    assert tool.plan(AgentRequest(request="Open unknown shell.exe")) == []
    assert "notepad" in tool.capabilities or tool.name == "desktop"


def test_high_risk_desktop_action_requires_confirmation(tmp_path):
    action = DesktopAction(type="wait", value="0", risk="high")
    assert requires_confirmation(action)
    result = DesktopTool(tmp_path).execute(type("Plan", (), {"parameters": {"action": action.model_dump()}})())
    assert result.status == "waiting_confirmation"
    assert result.requires_confirmation is True


ON_HOSTED_CI = os.environ.get("CI", "").lower() in {"true", "1"}


@pytest.mark.skipif(
    os.name != "nt" or ON_HOSTED_CI,
    reason=(
        "needs an interactive Windows desktop; hosted CI runners' rewritten "
        "Notepad launches and accepts typing but does not expose the typed "
        "text to the classic control readback (the test still runs on every "
        "Windows dev machine)"
    ),
)
def test_real_notepad_desktop_flow(tmp_path):
    tool = DesktopTool(tmp_path)
    plan = tool.plan(AgentRequest(request="Open Notepad and write ActionPilot desktop test"))
    try:
        launched = tool.execute(type("Plan", (), {"parameters": plan[0].parameters})())
        assert launched.status == "completed", launched.message
        typed = tool.execute(type("Plan", (), {"parameters": plan[1].parameters})())
        assert typed.status == "completed", typed.message
        assert Path(typed.output["screenshot"]).exists()
        assert any("ActionPilot desktop test" in f"{control.get('name', '')} {control.get('value', '')}" for control in typed.output.get("controls", []))
    finally:
        process = PROCESSES.get("notepad")
        if process and process.poll() is None:
            process.terminate()
