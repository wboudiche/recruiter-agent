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
    interviewed_at: datetime | None
    offer_at: datetime | None
    hired_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    awaiting_paste: bool = False
    # Why the pipeline stopped, when it did. Derived from the newest
    # event_logs row rather than stored — see `_latest_errors`.
    last_error: str | None = None
    # id of the event `last_error` came from. Two consecutive failures
    # often carry identical text (a recurring rate limit, an expired
    # token), so the message alone cannot tell "nothing new has happened"
    # apart from "it failed again the same way". The id can.
    last_error_event_id: int | None = None
    enrichment: dict | None = None


class ApplicationUpdate(BaseModel):
    stage: Literal[
        "scored", "validated", "rejected", "scheduled", "interviewed", "offer", "hired"
    ] | None = None
    notes: str | None = None
    # Free-text reason captured by the Reject dialog. Empty string clears
    # it; None leaves the existing value alone. Cleared automatically
    # when stage transitions away from rejected.
    rejection_reason: str | None = None
