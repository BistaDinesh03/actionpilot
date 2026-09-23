"""End-to-end agent task on the local account demo.

Natural-language request -> plan -> real browser execution -> observe ->
verify -> report. Everything runs against a hermetic local static server;
no external sites are contacted.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

ROOT = Path(__file__).resolve().parents[2]
REQUEST = "Open the local account demo and create an account for Demo User"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def account_demo_url():
    """Serve demo-site on an ephemeral port so tests never touch :4173."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(ROOT / "demo-site")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/account.html"
    deadline = time.time() + 8
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base, timeout=1) as response:
                ready = response.status == 200
            if ready:
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError("hermetic demo server did not become ready")
    yield base
    process.terminate()
    process.wait(timeout=5)


def wait_for(predicate, timeout=15, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def wait_status(client, run_id, wanted, timeout=25):
    if isinstance(wanted, str):
        wanted = {wanted}
    deadline = time.time() + timeout
    state = client.get(f"/api/runs/{run_id}").json()
    while time.time() < deadline:
        state = client.get(f"/api/runs/{run_id}").json()
        if state["status"] in wanted:
            return state
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} never reached {sorted(wanted)}; last status={state['status']} error={state.get('error')}")


def plan_and_execute(client, request, variables):
    plan = client.post("/api/agent/plan", json={"request": request, "variables": variables}).json()
    created = client.post("/api/agent/execute", json={"plan": plan, "approved": False}).json()
    return plan, created


def assert_sessions_closed(run_id):
    wait_for(lambda: run_id not in main.run_controls, timeout=10)
    assert main.agent_registry.get("browser")._sessions == {}


# --- planning ---------------------------------------------------------------


def test_local_account_plan_is_four_low_risk_steps_not_desktop(client):
    plan = main.current_agent_plan(REQUEST)
    assert plan.intent == "local_account"  # matched before the desktop regex
    assert plan.confidence == 0.95
    assert plan.requires_confirmation is False
    assert [step.action for step in plan.steps] == [
        "Open the local account demo page",
        "Fill the account form for Demo User",
        "Submit the account form",
        "Verify the account was created",
    ]
    assert all(step.tool == "browser" and step.risk == "low" for step in plan.steps)
    assert plan.steps[0].parameters["url"].endswith("/account.html")
    assert plan.steps[0].parameters["email"] == "demo.user@example.com"


def test_plan_variables_override_name_and_email(client):
    override = main.current_agent_plan("Create an account for a new tester", {"name": "Ada Lovelace"})
    fill = override.steps[1]
    assert fill.parameters["name"] == "Ada Lovelace"
    assert fill.parameters["email"] == "ada.lovelace@example.com"


def test_command_preview_returns_local_account_plan(client):
    body = client.post("/api/command", json={"command": "Create a local account for Demo User"}).json()
    assert body["intent"] == "local_account"
    assert body["matched"] is True
    assert body["agent_plan"]["intent"] == "local_account"
    assert len(body["agent_plan"]["steps"]) == 4
    assert body["agent_plan"]["requires_confirmation"] is False


def test_non_local_url_is_rejected_before_any_browser_work(client):
    plan, created = plan_and_execute(client, "Create an account for Demo User", {"url": "https://example.com/signup"})
    assert plan["intent"] == "local_account"
    assert created["status"] == "queued"
    final = wait_status(client, created["run_id"], "failed", timeout=30)
    assert "local" in (final.get("error") or "").lower()
    assert_sessions_closed(created["run_id"])


# --- end to end -------------------------------------------------------------


def test_local_account_runs_end_to_end_and_verifies(client, account_demo_url):
    plan, created = plan_and_execute(client, REQUEST, {"url": account_demo_url})
    assert created["status"] == "queued"
    run_id = created["run_id"]

    final = wait_status(client, run_id, "completed", timeout=60)
    assert not final.get("error"), final.get("error")

    labels = [step["label"] for step in final["steps"]]
    assert labels == [
        "Open the local account demo page",
        "Fill the account form for Demo User",
        "Submit the account form",
        "Verify the account was created",
    ]
    assert all(step["status"] == "completed" for step in final["steps"])

    # Evidence: every step captured a real screenshot and page location.
    for step in final["steps"]:
        assert step["screenshot_path"], step["label"]
        assert Path(step["screenshot_path"]).exists(), step["label"]
        assert (step["url"] or "").startswith("http://127.0.0.1:"), step["label"]

    # Verification was observed from the rendered result panel.
    verification = final["output"]["result"]["verification"]
    assert verification["passed"] is True
    assert verification["observed"]["name"] == "Demo User"
    assert verification["observed"]["email"] == "demo.user@example.com"
    assert "Demo User" in verification["summary"]

    events = [event["event"] for event in client.get("/api/activity", params={"limit": 200}).json()]
    for expected in ("agent_planned", "agent_run_started", "agent_step_started", "agent_step_completed", "agent_run_finished"):
        assert expected in events, expected

    assert_sessions_closed(run_id)


def test_verification_failure_reports_the_real_page_error(client, account_demo_url):
    plan, created = plan_and_execute(
        client, "Create an account for Demo User", {"url": account_demo_url, "email": "not-an-email"}
    )
    assert created["status"] == "queued"
    run_id = created["run_id"]

    final = wait_status(client, run_id, "failed", timeout=60)
    error = final.get("error") or ""
    assert "could not be verified" in error
    assert "Enter a valid email address" in error

    verify_step = final["steps"][-1]
    assert verify_step["label"] == "Verify the account was created"
    assert verify_step["status"] == "failed"
    verification = json.loads(verify_step["verification"])
    assert verification["passed"] is False
    assert any("Enter a valid email address" in message for message in verification.get("visible_errors", []))

    assert_sessions_closed(run_id)
