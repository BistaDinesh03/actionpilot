"""Pre-publication security hardening regression tests.

Each test pins one finding from the pre-publication audit:

- run errors no longer persist full tracebacks (they are served over the
  unauthenticated local API, leaking absolute paths and library versions);
- screenshot endpoints refuse paths that resolve outside ``runtime/`` so a
  poisoned database row cannot become an arbitrary file read;
- the phase-less browser observation branch refuses non-local URLs instead of
  navigating anywhere (it previously bypassed the local-only check);
- a web-research plan without a web-research step returns 400, not an
  unhandled 500 from ``next()``;
- plan and skill payloads are bounded;
- run titles mask secret-looking text, while the operational plan copy stays
  verbatim because an approved run resumes by re-planning from that exact
  text.
"""

import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.services.agent.browser_tool import BrowserTool
from app.services.agent.models import AgentPlan, PlanStep


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def make_completed_run(screenshot_path: str | None = None) -> str:
    run_id = main.uuid.uuid4().hex
    with main.db() as connection:
        connection.execute(
            "INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at, screenshot_path) VALUES (?, NULL, ?, 'completed', 0, '[]', ?, ?)",
            (run_id, "Hardening run", main.now(), screenshot_path),
        )
    return run_id


def add_step_screenshot(run_id: str, screenshot_path: str) -> None:
    with main.db() as connection:
        connection.execute(
            "INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at, screenshot_path) VALUES (?, ?, 0, 'step', 'navigate', 'completed', ?, ?)",
            (main.uuid.uuid4().hex, run_id, main.now(), screenshot_path),
        )


# --- run errors must not persist tracebacks ---------------------------------


def test_describe_error_is_type_plus_message():
    assert main.describe_error(ValueError("boom")) == "ValueError: boom"


def test_describe_error_never_contains_traceback_frames():
    message = main.describe_error(RuntimeError("kaboom"))
    assert "Traceback" not in message
    assert "File \"" not in message  # no interpreter frame paths
    assert "RuntimeError: kaboom" == message


def test_describe_error_redacts_and_bounds_long_messages():
    secret = "Sup3rSecretValue"
    message = main.describe_error(RuntimeError("login failed password=" + secret + " " + "x" * 900))
    assert secret not in message
    assert "[redacted]" in message
    assert len(message) <= len("RuntimeError: ") + 300


def test_main_module_no_longer_imports_traceback_for_run_errors():
    # Guards against re-introducing full tracebacks into persisted run errors.
    source = inspect.getsource(main)
    assert "format_exc" not in source


# --- screenshot endpoints refuse paths outside runtime/ ---------------------


def test_contained_runtime_path_accepts_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    inside = tmp_path / "runtime" / "runs" / "abc" / "shot.png"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"png")
    assert main.contained_runtime_path(inside) == inside.resolve()


def test_contained_runtime_path_rejects_everywhere_else(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    outside = tmp_path / "not-runtime.txt"
    outside.write_text("x", encoding="utf-8")
    assert main.contained_runtime_path(outside) is None
    assert main.contained_runtime_path(tmp_path / "runtime" / ".." / "secret.txt") is None
    assert main.contained_runtime_path("") is None


def test_run_screenshot_refuses_paths_outside_runtime(client, tmp_path):
    secret_file = tmp_path / "database-backup.txt"
    secret_file.write_text("private", encoding="utf-8")
    run_id = make_completed_run(screenshot_path=str(secret_file))
    # The file exists; only containment may refuse it.
    assert secret_file.is_file()
    assert client.get(f"/api/runs/{run_id}/screenshot").status_code == 404


def test_run_screenshot_still_serves_runtime_files(client, tmp_path):
    shot = tmp_path / "runtime" / "runs" / "abc" / "shot.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"\x89PNG-fake")
    run_id = make_completed_run(screenshot_path=str(shot))
    response = client.get(f"/api/runs/{run_id}/screenshot")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_step_screenshot_refuses_paths_outside_runtime(client, tmp_path):
    secret_file = tmp_path / "user-notes.txt"
    secret_file.write_text("private", encoding="utf-8")
    run_id = make_completed_run()
    add_step_screenshot(run_id, str(secret_file))
    assert client.get(f"/api/runs/{run_id}/step/0/screenshot").status_code == 404


def test_step_screenshot_still_serves_runtime_files(client, tmp_path):
    shot = tmp_path / "runtime" / "runs" / "abc" / "step0.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"\x89PNG-fake")
    run_id = make_completed_run()
    add_step_screenshot(run_id, str(shot))
    assert client.get(f"/api/runs/{run_id}/step/0/screenshot").status_code == 200


# --- browser observation stays local-only -----------------------------------


def test_browser_observation_refuses_external_urls(tmp_path):
    tool = BrowserTool(tmp_path)
    step = PlanStep(tool="browser", action="observe the page", parameters={"url": "https://example.com/page"})
    result = tool.execute(step)
    assert result.status == "failed"
    assert result.output.get("url_allowed") is False
    assert "local demo site" in result.message


def test_browser_observation_refuses_file_scheme(tmp_path):
    tool = BrowserTool(tmp_path)
    step = PlanStep(tool="browser", action="observe the page", parameters={"url": "file:///etc/passwd"})
    result = tool.execute(step)
    assert result.status == "failed"
    assert result.output.get("url_allowed") is False


def test_browser_observation_refuses_loopback_lookalike_hosts(tmp_path):
    tool = BrowserTool(tmp_path)
    step = PlanStep(tool="browser", action="observe", parameters={"url": "http://localhost.evil.example/"})
    assert tool.execute(step).status == "failed"


# --- malformed plans fail cleanly -------------------------------------------


def web_research_plan_without_matching_step() -> dict:
    return {
        "plan": {
            "request": "research something",
            "intent": "web_research",
            "confidence": 0.9,
            "steps": [{"tool": "desktop", "action": "open notepad", "risk": "low", "parameters": {}}],
        },
        "approved": False,
    }


def test_web_research_plan_without_step_returns_400_not_500(client):
    response = client.post("/api/agent/execute", json=web_research_plan_without_matching_step())
    assert response.status_code == 400
    assert "web_research" in response.json()["detail"]


def test_agent_plan_rejects_oversized_request():
    with pytest.raises(ValidationError):
        AgentPlan(request="x" * 4001, intent="web_research", confidence=0.9, steps=[])


def test_agent_plan_rejects_too_many_steps():
    steps = [PlanStep(tool="browser", action=f"step {i}", risk="low") for i in range(51)]
    with pytest.raises(ValidationError):
        AgentPlan(request="do a thing", intent="web_research", confidence=0.9, steps=steps)


def test_agent_plan_still_accepts_realistic_plans():
    steps = [PlanStep(tool="browser", action=f"step {i}", risk="low") for i in range(15)]
    plan = AgentPlan(request="do a thing", intent="local_account", confidence=0.9, steps=steps)
    assert len(plan.steps) == 15


def test_skill_creation_rejects_unbounded_step_lists(client):
    payload = {
        "name": "Huge skill",
        "description": "",
        "steps": [{"type": "navigate", "url": "http://127.0.0.1:4174", "label": f"s{i}"} for i in range(501)],
    }
    assert client.post("/api/skills", json=payload).status_code == 422


# --- run titles mask secrets; the operational plan copy stays verbatim ------


def secret_plan() -> AgentPlan:
    return AgentPlan(
        request="log in with password=Hunter2 to the demo",
        intent="local_account",
        confidence=1.0,
        steps=[PlanStep(tool="browser", action="Fill the account form", risk="low")],
    )


def test_run_title_masks_secret_assignments(client):
    run = main.create_agent_run(secret_plan(), "completed", {})
    assert "Hunter2" not in run["task_name"]
    assert "[redacted]" in run["task_name"]
    assert "log in with" in run["task_name"]


def test_task_title_helper_matches_audit_redaction():
    assert main.task_title("open the demo password=Hunter2") == "open the demo password=[redacted]"
    assert len(main.task_title("y" * 400)) == 120


def test_operational_plan_copy_stays_verbatim_for_resume(client):
    # Deliberate boundary: resume_upfront_run re-plans from the stored request,
    # so the runs.plan copy keeps the original text while the displayed title
    # is masked. Documented in SECURITY.md.
    run = main.create_agent_run(secret_plan(), "completed", {})
    with main.db() as connection:
        row = connection.execute("SELECT plan FROM runs WHERE id = ?", (run["id"],)).fetchone()
    stored = json.loads(row["plan"])
    assert stored["request"] == "log in with password=Hunter2 to the demo"
