from datetime import datetime

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
    created_at: datetime
    updated_at: datetime
