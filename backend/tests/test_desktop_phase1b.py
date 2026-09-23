import os

import pytest

from app.services.agent.models import AgentRequest
from app.services.desktop.tool import DesktopTool


def _plan(parameters):
    return type("Plan", (), {"parameters": {"action": parameters}})()


def test_targetless_wait_completes_without_semantic_target(tmp_path):
    result = DesktopTool(tmp_path).execute(_plan({"type": "wait", "value": "0"}))
    assert result.status == "completed"
    assert "semantic desktop target" not in (result.message or "")


def test_targetless_screenshot_completes_without_semantic_target(tmp_path):
    result = DesktopTool(tmp_path).execute(_plan({"type": "take_screenshot"}))
    assert result.status == "completed"
    assert "semantic desktop target" not in (result.message or "")
    assert "screenshot" in result.output


def test_delete_file_returns_honest_failure_and_preserves_file(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text("keep me", encoding="utf-8")
    tool = DesktopTool(tmp_path)
    unapproved = tool.execute(_plan({"type": "delete_file", "value": str(canary)}))
    approved = tool.execute(_plan({"type": "delete_file", "value": str(canary)}), approved=True)
    for result in (unapproved, approved):
        assert result.status == "failed"
        assert result.message == "Delete file is not yet supported."
    assert canary.exists()
    assert canary.read_text(encoding="utf-8") == "keep me"


def test_delete_plan_emits_delete_file_and_stays_high_risk(tmp_path):
    steps = DesktopTool(tmp_path).plan(AgentRequest(request="Open notepad and delete the requested file"))
    delete_steps = [step for step in steps if step.action == "Delete the requested file"]
    assert len(delete_steps) == 1
    assert delete_steps[0].parameters["action"]["type"] == "delete_file"
    assert delete_steps[0].risk == "high"


@pytest.mark.skipif(os.name != "nt", reason="Windows UI Automation is only available on Windows")
def test_targetless_click_still_requires_semantic_target(tmp_path):
    result = DesktopTool(tmp_path).execute(_plan({"type": "click"}))
    assert result.status == "failed"
    assert result.message == "A semantic desktop target is required"
