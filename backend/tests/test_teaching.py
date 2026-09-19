import json

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.teach_sessions.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def test_teach_persists_real_actions_and_skips_password(client):
    started = client.post("/api/teach/start", json={"name": "Demo Keyboard Search", "description": "Record demo shop"})
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    action = {
        "type": "click",
        "timestamp": "2026-09-19T12:00:00Z",
        "url": "http://127.0.0.1:4173/",
        "title": "Demo Shop",
        "target": {"tag": "button", "role": "button", "name": "Open product", "css": "[data-testid=keyboard]"},
    }
    assert client.post(f"/api/teach/{session_id}/action", json=action).json()["recorded"] is True
    blocked = {**action, "type": "type", "value": "never-store", "input_type": "password", "label": "Password"}
    response = client.post(f"/api/teach/{session_id}/action", json=blocked)
    assert response.status_code == 200
    assert response.json()["recorded"] is False
    finished = client.post(f"/api/teach/{session_id}/finish")
    assert finished.status_code == 200
    skill = finished.json()
    assert skill["name"] == "Demo Keyboard Search"
    assert len(skill["steps"]) == 1
    assert "never-store" not in json.dumps(skill)
    stored = client.get(f"/api/skills/{skill['id']}").json()
    assert stored["steps"][0]["target"]["name"] == "Open product"


def test_malformed_action_is_rejected(client):
    session_id = client.post("/api/teach/start", json={"name": "Invalid action"}).json()["session_id"]
    response = client.post(f"/api/teach/{session_id}/action", json={"type": "shell", "label": "No"})
    assert response.status_code == 422


def test_expired_session_is_rejected(client):
    response = client.post("/api/teach/not-a-session/action", json={"type": "navigate", "url": "https://example.com"})
    assert response.status_code == 404
