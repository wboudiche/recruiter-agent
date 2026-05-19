from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ScoreBreakdownItem(BaseModel):
    criterion: str
    weight: float
    score: int
    rationale: str


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    candidate_id: int
    stage: str
    score: int | None
    score_breakdown: list[ScoreBreakdownItem] | None
    score_rationale: str | None
    notes: str | None
    validated_at: datetime | None
    invited_at: datetime | None
    scheduled_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    awaiting_paste: bool = False
    enrichment: dict | None = None


class ApplicationUpdate(BaseModel):
    stage: Literal["scored", "validated", "rejected"] | None = None
    notes: str | None = None
    # Free-text reason captured by the Reject dialog. Empty string clears
    # it; None leaves the existing value alone. Cleared automatically
    # when stage transitions away from rejected.
    rejection_reason: str | None = None
