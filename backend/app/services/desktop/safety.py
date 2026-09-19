from __future__ import annotations

from .models import DesktopAction

HIGH_WORDS = ("delete", "installer", "install", "system setting", "security", "publish", "send", "purchase")


def risk_for(action: DesktopAction) -> str:
    text = f"{action.type} {action.value or ''} {action.application_id or ''}".lower()
    if action.risk == "high" or any(word in text for word in HIGH_WORDS):
        return "high"
    if action.risk == "medium":
        return "medium"
    return "low"


def requires_confirmation(action: DesktopAction) -> bool:
    return risk_for(action) == "high"
