import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.services.ai.provider import StructuredIntent
from app.services.matching.matcher import match_command

ROOT = Path(__file__).resolve().parents[2]


def skill(name: str, description: str = "", value: str = "keyboard"):
    return {"id": name.lower().replace(" ", "-"), "name": name, "description": description, "domains": ["127.0.0.1:4173"], "steps": [{"type": "type", "label": "Search product", "target": {"role": "textbox", "placeholder": "Search products"}, "value": value}]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def test_exact_and_fuzzy_skill_match():
    skills = [skill("Demo Keyboard Search", "Search the demo shop")]
    exact = match_command("Run Demo Keyboard Search", skills)
    fuzzy = match_command("Do my keyboard workflow", skills)
    assert exact["intent"] == "run_skill"
    assert exact["confidence"] > 0.7
    assert fuzzy["skill_id"] == skills[0]["id"]


def test_variable_extraction_and_safe_plan_substitution():
    result = match_command("Run my keyboard workflow for a mouse", [skill("Demo Keyboard Search")])
    assert result["variables"] == {"product": "mouse"}
    assert result["plan"][0]["value"] == "mouse"
    assert result["plan"][0]["target"]["placeholder"] == "Search products"

    explicit = match_command("Run Demo Keyboard Search with product = white keyboard", [skill("Demo Keyboard Search")])
    assert explicit["variables"] == {"product": "white keyboard"}
    assert explicit["plan"][0]["value"] == "white keyboard"


def test_ambiguous_and_unknown_commands():
    ambiguous = match_command("Run keyboard workflow", [skill("Keyboard Flow"), skill("Keyboard Search")])
    unknown = match_command("Run my calendar task", [skill("Demo Keyboard Search")])
    assert ambiguous["intent"] == "clarify"
    assert ambiguous["message"] == "Which skill should I run?"
    assert unknown["matched"] is False


def test_malformed_ai_response_is_rejected():
    with pytest.raises(ValidationError):
        StructuredIntent.model_validate({"intent": "run_shell", "confidence": 3, "variables": []})


def test_command_creates_run_without_bypassing_plan(client):
    created = client.post("/api/skills", json={"name": "Demo Keyboard Search", "steps": [{"type": "type", "label": "Search", "target": {"role": "textbox", "placeholder": "Search products"}, "value": "keyboard"}]}).json()
    response = client.post("/api/command", json={"command": "Run my keyboard workflow for a mouse", "execute": True})
    body = response.json()
    assert body["intent"] == "run_skill"
    assert body["skill_id"] == created["id"]
    assert body["variables"] == {"product": "mouse"}
    assert body["run_id"]


def test_command_to_real_playwright_execution(client):
    process = subprocess.Popen([sys.executable, "-m", "http.server", "4173", "--directory", str(ROOT / "demo-site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        steps = [
            {"type": "navigate", "label": "Open Demo Shop", "url": "http://127.0.0.1:4173"},
            {"type": "type", "label": "Search product", "target": {"role": "textbox", "placeholder": "Search products"}, "value": "keyboard"},
            {"type": "click", "label": "Open product", "target": {"role": "button", "name": "Open product"}},
            {"type": "select", "label": "Select variant", "target": {"role": "combobox", "name": "Variant"}, "value": "Black"},
            {"type": "click", "label": "Add to cart", "target": {"role": "button", "name": "Add to cart"}},
        ]
        skill_response = client.post("/api/skills", json={"name": "Demo Keyboard Search", "description": "Search demo products", "steps": steps}).json()
        command = client.post("/api/command", json={"command": "Run my keyboard workflow for a mouse", "execute": True}).json()
        assert command["skill_id"] == skill_response["id"]
        assert command["variables"] == {"product": "mouse"}
        deadline = time.time() + 20
        state = client.get(f"/api/runs/{command['run_id']}").json()
        while state["status"] in {"queued", "running"} and time.time() < deadline:
            time.sleep(0.2)
            state = client.get(f"/api/runs/{command['run_id']}").json()
        assert state["status"] == "completed", state
        assert json.loads(state["steps"][-1]["verification"])["cart_count"] == "1"
    finally:
        process.terminate()
        process.wait(timeout=5)
