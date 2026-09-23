import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    main.teach_sessions.clear()
    main.run_controls.clear()
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def make_run() -> str:
    run_id = uuid.uuid4().hex
    with main.db() as connection:
        connection.execute(
            "INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at) VALUES (?, NULL, ?, 'completed', 0, '[]', ?)",
            (run_id, "Video endpoint run", main.now()),
        )
    return run_id


def write_video(run_id: str, content: bytes) -> None:
    directory = main.ROOT / "runtime" / "runs" / run_id / "video"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recording.webm").write_bytes(content)


def test_empty_recording_with_range_returns_empty_200_not_416(client):
    # The recorder is still writing: a 0-byte file must never answer 416.
    run_id = make_run()
    write_video(run_id, b"")
    response = client.get(f"/api/runs/{run_id}/video", headers={"Range": "bytes=0-"})
    assert response.status_code == 200
    assert response.content == b""


def test_completed_recording_without_range_returns_full_body(client):
    run_id = make_run()
    write_video(run_id, b"webm-bytes-here")
    response = client.get(f"/api/runs/{run_id}/video")
    assert response.status_code == 200
    assert response.content == b"webm-bytes-here"
    assert response.headers.get("accept-ranges") == "bytes"


def test_completed_recording_honours_explicit_range_with_206(client):
    run_id = make_run()
    write_video(run_id, b"0123456789")
    response = client.get(f"/api/runs/{run_id}/video", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["content-range"] == "bytes 0-3/10"


def test_completed_recording_honours_open_ended_range_with_206(client):
    run_id = make_run()
    write_video(run_id, b"0123456789")
    response = client.get(f"/api/runs/{run_id}/video", headers={"Range": "bytes=0-"})
    assert response.status_code == 206
    assert response.content == b"0123456789"
    assert response.headers["content-range"] == "bytes 0-9/10"


def test_missing_recording_returns_404(client):
    run_id = make_run()
    response = client.get(f"/api/runs/{run_id}/video")
    assert response.status_code == 404
