import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.execution.executor import BrowserExecutor, ConfirmationRequired
from app.services.execution.locator import resolve_locator
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def demo_server():
    process = subprocess.Popen([sys.executable, "-m", "http.server", "4173", "--directory", str(ROOT / "demo-site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    yield "http://127.0.0.1:4173"
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def demo_steps(base_url: str):
    return [
        {"type": "navigate", "label": "Open Demo Shop", "url": base_url},
        {"type": "type", "label": "Search keyboard", "target": {"role": "textbox", "placeholder": "Search products"}, "value": "keyboard"},
        {"type": "click", "label": "Open keyboard product", "target": {"role": "button", "name": "Open product"}},
        {"type": "select", "label": "Select variant", "target": {"role": "combobox", "name": "Variant"}, "value": "Black"},
        {"type": "click", "label": "Add to cart", "target": {"role": "button", "name": "Add to cart"}},
    ]


def test_locator_fallback_and_variable_substitution():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="query">Search</label><input id="query" placeholder="Find item"><button>Go</button>')
        locator, strategy = resolve_locator(page, {"label": "Search", "placeholder": "Find item"})
        assert strategy == "label"
        assert locator.is_visible()
        assert BrowserExecutor.substitute("{product}", {"product": "mouse"}) == "mouse"
        browser.close()


def test_high_risk_action_is_blocked(tmp_path):
    executor = BrowserExecutor(tmp_path)
    with pytest.raises(ConfirmationRequired, match="Confirmation required"):
        executor.execute([{ "type": "click", "label": "Final purchase", "risk_level": "high", "target": {"role": "button", "name": "Buy"}}])


def test_real_demo_replay_completes_and_changes_cart(client, demo_server, tmp_path):
    skill = client.post("/api/skills", json={"name": "Demo Keyboard Search", "steps": demo_steps(demo_server), "domains": ["127.0.0.1:4173"]}).json()
    run = client.post("/api/runs", json={"skill_id": skill["id"]}).json()
    deadline = time.time() + 20
    state = client.get(f"/api/runs/{run['id']}").json()
    while state["status"] in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.2)
        state = client.get(f"/api/runs/{run['id']}").json()
    assert state["status"] == "completed", state
    assert len(state["steps"]) == 5
    assert all(step["status"] == "completed" for step in state["steps"])
    assert json.loads(state["steps"][-1]["verification"])["cart_count"] == "1"


def test_invalid_locator_fails_with_screenshot(client, demo_server):
    skill = client.post("/api/skills", json={"name": "Broken", "steps": [{"type": "navigate", "label": "Open", "url": demo_server}, {"type": "click", "label": "Missing", "target": {"role": "button", "name": "Does not exist"}}]}).json()
    run = client.post("/api/runs", json={"skill_id": skill["id"]}).json()
    deadline = time.time() + 20
    state = client.get(f"/api/runs/{run['id']}").json()
    while state["status"] in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.2)
        state = client.get(f"/api/runs/{run['id']}").json()
    assert state["status"] == "failed"
    assert state["steps"][-1]["screenshot_path"]
    assert Path(state["steps"][-1]["screenshot_path"]).exists()


def test_stop_endpoint_marks_run_stopped(client, demo_server):
    skill = client.post("/api/skills", json={"name": "Long", "steps": [{"type": "navigate", "label": "Open", "url": demo_server}, {"type": "wait", "label": "Wait", "value": "5000"}]}).json()
    run = client.post("/api/runs", json={"skill_id": skill["id"]}).json()
    time.sleep(0.3)
    stopped = client.post(f"/api/runs/{run['id']}/stop").json()
    assert stopped["status"] == "stopped"
