from __future__ import annotations

RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "waiting_confirmation",
    "paused",
    "completed",
    "failed",
    "stopped",
)

TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "stopped"})

# Allowed transitions out of each non-terminal status. Terminal statuses are
# final: nothing may restart, resume, or overwrite them.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "waiting_confirmation", "paused", "completed", "failed", "stopped"}),
    "running": frozenset({"waiting_confirmation", "paused", "completed", "failed", "stopped"}),
    "waiting_confirmation": frozenset({"running", "paused", "completed", "failed", "stopped"}),
    "paused": frozenset({"running", "waiting_confirmation", "failed", "stopped"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "stopped": frozenset(),
}


class InvalidTransition(RuntimeError):
    """Raised when a run is asked to move to a status its current status forbids."""


def validate_transition(current: str, new: str) -> None:
    if new not in RUN_STATUSES:
        raise InvalidTransition(f"Unknown run status: {new!r}")
    if current == new:
        # Writing the same status again is an idempotent no-op.
        return
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTransition(f"Unknown current run status: {current!r}")
    if new not in allowed:
        raise InvalidTransition(f"Invalid run transition: {current!r} -> {new!r}")
