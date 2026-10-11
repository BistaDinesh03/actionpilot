"""Documented configuration must actually work.

The repo-root .env is loaded at startup, shell environment wins over it,
and .env.example only documents variables the backend really reads (a
previous version listed GMAIL_*/ACTIONPILOT_AI_PROVIDER that no code read).
"""

import os
from pathlib import Path

from app import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_dotenv_sets_missing_variables(monkeypatch, tmp_path):
    monkeypatch.delenv("ACTIONPILOT_TEST_SENTINEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ACTIONPILOT_TEST_SENTINEL=loaded\n", encoding="utf-8")
    main.load_dotenv(env_file, override=False)
    assert os.getenv("ACTIONPILOT_TEST_SENTINEL") == "loaded"


def test_shell_environment_still_wins_over_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_AGENT_STEPS", "21")
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_AGENT_STEPS=7\n", encoding="utf-8")
    main.load_dotenv(env_file, override=False)
    assert os.getenv("MAX_AGENT_STEPS") == "21"


def test_startup_loads_the_repo_root_dotenv():
    # Every test imports app.main without a repo-root .env present, so the
    # import-time call must be a safe no-op; pin the wiring itself.
    source = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'load_dotenv(ROOT / ".env")' in source


def test_env_example_only_documents_variables_the_backend_reads():
    example = REPO_ROOT / ".env.example"
    keys = [
        line.split("=", 1)[0].strip()
        for line in example.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    ]
    assert keys, "the example file must document the real configuration surface"
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (REPO_ROOT / "backend" / "app").rglob("*.py")
    )
    for key in keys:
        assert f'"{key}"' in sources or f"'{key}'" in sources, f"{key} is documented but never read by the backend"
