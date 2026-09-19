from __future__ import annotations

from pydantic import BaseModel, Field


class VisualRegion(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    description: str


class VisualTarget(BaseModel):
    target: VisualRegion
    confidence: float = Field(ge=0, le=1)


def accept_visual_target(candidate: VisualTarget, minimum_confidence: float = 0.9) -> VisualTarget:
    if candidate.confidence < minimum_confidence:
        raise ValueError("Visual target confidence is below the safe threshold")
    return candidate
