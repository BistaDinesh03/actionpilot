"""Deterministic, bounded recovery decisions (Milestone E).

After a failed step the loop asks this classifier — never an AI — which of
five bounded outcomes applies: retry_after_delay, reobserve, replan, stop,
or ask. Every rule derives from data that already exists (step metadata,
the tool result, its structured verification), every delay is short and
interruptible, and every decision stays counted against the Milestone A
budgets, so no run can loop forever.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import PlanStep, ToolResult

# Short, interruptible pause before any bounded retry.
RETRY_DELAY_SECONDS = 0.25

RecoveryKind = Literal["retry_after_delay", "reobserve", "replan", "stop", "ask"]

_VERIFICATION_MARKERS = ("could not be verified", "verification failed")
_UNSUPPORTED_MARKERS = ("not yet supported",)
_TARGET_MARKERS = ("target not found", "ambiguous", "stable selector")
_HUMAN_MARKERS = ("permission", "unauthorized", "credential", "forbidden", "access denied", "not logged in")


class RecoveryDecision(BaseModel):
    """One bounded recovery outcome for a failed step."""

    kind: RecoveryKind
    reason: str
    delay: float = Field(default=0.0, ge=0.0, le=5.0)


def classify_recovery(
    step: PlanStep,
    result: ToolResult,
    *,
    attempt: int,
    budget: int,
    can_reobserve: bool = False,
    can_replan: bool = False,
) -> RecoveryDecision:
    """Classify a failed step into a single bounded recovery decision.

    Purely deterministic: the same step, result, and attempt always produce
    the same decision, and no decision may exceed the caller's budgets.
    """
    message = str(result.message or "").lower()
    verification = result.output.get("verification") if isinstance(result.output, dict) else None

    # Risky/destructive failures never retry and never silently escalate.
    if step.risk == "high":
        return RecoveryDecision(kind="stop", reason="Risky steps are never retried automatically; the failure is reported honestly.")
    # A judgement of failure does not change by repeating it.
    if (isinstance(verification, dict) and verification.get("passed") is False) or any(marker in message for marker in _VERIFICATION_MARKERS):
        return RecoveryDecision(kind="stop", reason="The verification already judged the outcome unsuccessful; repeating it would not change the page.")
    # Determinately unsupported or unsafe-to-guess outcomes: never loop.
    if any(marker in message for marker in _UNSUPPORTED_MARKERS):
        return RecoveryDecision(kind="stop", reason="This action is not supported yet; retrying cannot succeed.")
    if any(marker in message for marker in _TARGET_MARKERS):
        return RecoveryDecision(kind="stop", reason="A fresh observation already ruled out a safe target; never guess.")
    # Some failures genuinely require a human decision first.
    if any(marker in message for marker in _HUMAN_MARKERS):
        return RecoveryDecision(kind="ask", reason="This failure needs a human decision before anything else happens.", delay=0.0)
    # The bounded budgets are authoritative.
    if attempt >= budget:
        return RecoveryDecision(kind="stop", reason="The bounded retry budget for this step is exhausted.")
    if attempt == 0:
        return RecoveryDecision(kind="retry_after_delay", reason="Read-only step failed; one bounded delayed retry is safe.", delay=RETRY_DELAY_SECONDS)
    if can_replan:
        return RecoveryDecision(kind="replan", reason="Re-observe and re-decide the target before the next bounded attempt.", delay=RETRY_DELAY_SECONDS)
    if can_reobserve:
        return RecoveryDecision(kind="reobserve", reason="Re-observe the environment before the next bounded attempt.", delay=RETRY_DELAY_SECONDS)
    return RecoveryDecision(kind="retry_after_delay", reason="Read-only step failed; another bounded delayed retry is safe.", delay=RETRY_DELAY_SECONDS)
