from __future__ import annotations

from .action import ComputerAction


def requires_confirmation(action: ComputerAction) -> bool:
    if action.risk == "high":
        return True
    return any(word in f"{action.action} {action.value or ''}".lower() for word in ("delete", "purchase", "send", "publish", "security"))
