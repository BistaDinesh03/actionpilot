from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RoutineStore:
    def __init__(self, db_path: Any) -> None:
        self.db_path = db_path
        with self._db() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS routines (id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, schedule TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_run TEXT, next_run TEXT)")

    def _db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            return [{**dict(row), "enabled": bool(row["enabled"])} for row in connection.execute("SELECT * FROM routines ORDER BY name")]

    def create(self, name: str, prompt: str, schedule: str, enabled: bool = True) -> dict[str, Any]:
        item = {"id": str(uuid.uuid4()), "name": name, "prompt": prompt, "schedule": schedule, "enabled": enabled, "last_run": None, "next_run": None}
        with self._db() as connection:
            connection.execute("INSERT INTO routines VALUES (?, ?, ?, ?, ?, ?, ?)", (item["id"], name, prompt, schedule, int(enabled), None, None))
        return item

    def update(self, routine_id: str, name: str, prompt: str, schedule: str, enabled: bool) -> dict[str, Any] | None:
        with self._db() as connection:
            connection.execute("UPDATE routines SET name = ?, prompt = ?, schedule = ?, enabled = ? WHERE id = ?", (name, prompt, schedule, int(enabled), routine_id))
        return next((item for item in self.list() if item["id"] == routine_id), None)

    def delete(self, routine_id: str) -> bool:
        with self._db() as connection:
            return connection.execute("DELETE FROM routines WHERE id = ?", (routine_id,)).rowcount > 0

    def mark_run(self, routine_id: str) -> None:
        with self._db() as connection:
            connection.execute("UPDATE routines SET last_run = ? WHERE id = ?", (_now(), routine_id))
