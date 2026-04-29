from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class Stage(str, Enum):
    SOURCED = "sourced"      # reserved for Phase 2 bulk; unused in Phase 1
    EXTRACTING = "extracting"
    SCORED = "scored"
    VALIDATED = "validated"
    INVITED = "invited"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    stage: Mapped[Stage] = mapped_column(SAEnum(Stage, name="stage"))
    score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[list[dict] | None] = mapped_column(JSON)
    score_rationale: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
