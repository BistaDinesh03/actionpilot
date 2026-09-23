"""Startup run reconciliation (Phase 1A): on backend startup every persisted
run that is queued/running/waiting_confirmation/paused is transitioned to
failed with error "Interrupted by backend restart" plus one run_interrupted
audit event. Terminal runs stay untouched, an empty database is a safe no-op,
and rerunning reconciliation never modifies already-failed runs or creates
duplicate audit events."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.agent.models import AgentPlan, PlanStep

RESTART_ERROR = "Interrupted by backend restart"
AUDIT_EVENT = "run_interrupted"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "reconcile.db")
    main.run_controls.clear()
    main.init_db()
    return main.DB_PATH


def seed_run(status="queued"):
    """Persist a run at the given status without spawning any executor thread."""
    plan = AgentPlan(
        request="Reconciliation seed run",
        intent="test",
        confidence=1.0,
        steps=[PlanStep(tool="fake", action="seed step", risk="low")],
    )
    run_id = main.create_pending_agent_run(plan)
    if status != "queued":
        main.set_run(run_id, status)
    return run_id


def run_row(run_id):
    with main.db() as connection:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def audit_count(event=AUDIT_EVENT, detail=None):
    with main.db() as connection:
        if detail is None:
            return connection.execute("SELECT COUNT(*) FROM audit_logs WHERE event = ?", (event,)).fetchone()[0]
        return connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE event = ? AND detail = ?",
            (event, detail),
        ).fetchone()[0]


def run_count():
    with main.db() as connection:
        return connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def boot():
    """Enter the app so the real startup hook (init_db + reconciliation) runs."""
    with TestClient(main.app):
        pass


# A: running run -------------------------------------------------------------


def test_startup_marks_running_run_failed_with_error_and_audit(fresh_db):
    run_id = seed_run("running")
    boot()
    row = run_row(run_id)
    assert row["status"] == "failed"
    assert row["error"] == RESTART_ERROR
    assert audit_count(detail="Reconciliation seed run") == 1


# B, C, D: queued / waiting_confirmation / paused ---------------------------


@pytest.mark.parametrize(
    "status",
    ["queued", "waiting_confirmation", "paused"],
    ids=["queued", "waiting_confirmation", "paused"],
)
def test_startup_fails_each_non_terminal_status(fresh_db, status):
    run_id = seed_run(status)
    assert run_row(run_id)["status"] == status
    assert main.reconcile_interrupted_runs() == 1
    row = run_row(run_id)
    assert row["status"] == "failed"
    assert row["error"] == RESTART_ERROR
    assert audit_count() == 1


# E: terminal runs stay untouched -------------------------------------------


def test_terminal_runs_are_untouched(fresh_db):
    completed = seed_run("completed")
    failed = seed_run("failed")
    main.set_run(failed, "failed", error="original failure")
    stopped = seed_run("stopped")

    assert main.reconcile_interrupted_runs() == 0

    assert run_row(completed)["status"] == "completed"
    assert run_row(completed)["error"] is None
    assert run_row(failed)["status"] == "failed"
    assert run_row(failed)["error"] == "original failure"
    assert run_row(stopped)["status"] == "stopped"
    assert audit_count() == 0


# F: idempotency -------------------------------------------------------------


def test_reconciliation_is_idempotent(fresh_db):
    run_id = seed_run("running")
    boot()  # first reconciliation via the real startup hook
    assert audit_count() == 1
    assert main.reconcile_interrupted_runs() == 0  # direct rerun selects nothing
    boot()  # second startup: still nothing to reconcile
    assert audit_count() == 1
    row = run_row(run_id)
    assert row["status"] == "failed"
    assert row["error"] == RESTART_ERROR


# G: empty database ----------------------------------------------------------


def test_reconciliation_on_empty_database(fresh_db):
    assert run_count() == 0
    assert main.reconcile_interrupted_runs() == 0
    boot()  # startup succeeds with no interrupted runs
    assert run_count() == 0
    assert audit_count() == 0
