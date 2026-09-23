from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable


@dataclass
class ExecutionContext:
    stop_event: Event
    pause_event: Event
    timeout_ms: int = 10_000
    variables: dict[str, str] = field(default_factory=dict)


@dataclass
class StepOutcome:
    status: str
    step_index: int
    message: str = ""
    screenshot_path: str | None = None
    url: str | None = None
    title: str | None = None


ProgressCallback = Callable[[str, int, dict[str, Any]], None]

# Approval gate invoked before a high-risk step runs. Returns None when the
# user approved the step, or a human-readable reason to stop when they did not.
ApprovalGate = Callable[[int, dict[str, Any]], str | None]
