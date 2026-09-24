from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]

# Hard bound for the deterministic decision seam: a step may be re-targeted
# at most once per decision. There is no retry loop inside deciding.
MAX_RETARGETS = 1


class Decision(BaseModel):
    """Deterministic outcome of the observe -> decide seam.

    execute: the planned step is still valid in the fresh observation.
    retarget: a single safe, deterministic match was established instead.
    fail: no safe match exists; the step must fail honestly, not guess.
    """

    kind: Literal["execute", "retarget", "fail"]
    reason: str = ""
    target: dict[str, Any] | None = None
    replans: int = Field(default=0, ge=0, le=MAX_RETARGETS)


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class VerificationResult(BaseModel):
    """Structured answer to: did the intended thing actually happen?

    Recorded for completed agent actions from deterministic checks against
    local evidence; never inferred, never fabricated.
    """

    passed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    # Passthroughs used by the existing local-account verification logic.
    observed: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    visible_errors: list[str] = Field(default_factory=list)

    @classmethod
    def from_checks(
        cls,
        checks: dict[str, bool],
        *,
        summary: str = "",
        evidence: list[str] | None = None,
        observed: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        visible_errors: list[str] | None = None,
    ) -> "VerificationResult":
        return cls(
            passed=bool(checks) and all(checks.values()),
            checks=[VerificationCheck(name=name, passed=bool(ok)) for name, ok in checks.items()],
            summary=summary,
            evidence=list(evidence or []),
            observed=observed,
            expected=expected,
            visible_errors=list(visible_errors or []),
        )


class AgentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    variables: dict[str, str] = Field(default_factory=dict)


class PlanStep(BaseModel):
    tool: str
    action: str
    risk: RiskLevel = "low"
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    request: str
    intent: str
    confidence: float = Field(ge=0, le=1)
    steps: list[PlanStep]
    variables: dict[str, str] = Field(default_factory=dict)
    requires_confirmation: bool = False
    message: str | None = None


class ToolResult(BaseModel):
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    message: str | None = None
    next_steps: list[PlanStep] = Field(default_factory=list)
