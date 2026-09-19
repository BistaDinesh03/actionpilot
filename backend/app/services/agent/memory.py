from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: Any) -> None:
        self.db_path = db_path
        with self._db() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL, last_used TEXT)")

    def _db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list(self) -> list[dict[str, Any]]:
        with self._db() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM memories ORDER BY created_at DESC")]

    def create(self, memory_type: str, title: str, value: str) -> dict[str, Any]:
        item = {"id": str(uuid.uuid4()), "type": memory_type, "title": title, "value": value, "created_at": _now(), "last_used": None}
        with self._db() as connection:
            connection.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?)", tuple(item.values()))
        return item

    def update(self, memory_id: str, title: str, value: str, memory_type: str) -> dict[str, Any] | None:
        with self._db() as connection:
            connection.execute("UPDATE memories SET type = ?, title = ?, value = ? WHERE id = ?", (memory_type, title, value, memory_id))
        return next((item for item in self.list() if item["id"] == memory_id), None)

    def delete(self, memory_id: str) -> bool:
        with self._db() as connection:
            return connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount > 0

    def relevant(self, request: str) -> list[dict[str, Any]]:
        terms = {term.lower() for term in request.split() if len(term) > 3}
        items = self.list()
        return [item for item in items if any(term in f"{item['title']} {item['value']}".lower() for term in terms)]
