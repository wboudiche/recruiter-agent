from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class InterviewKitRow(Base):
    """One question list, for one round and one track of one application.

    Named with a Row suffix on purpose: `InterviewKit` is the Pydantic
    schema in schemas/interview.py, and api/interview.py imports both.

    Sheets live on `interview_assignments` and are matched to their kit by
    (application_id, round, track) — a sheet's answers are keyed by the
    question ids in `questions`, so the two must always be read as a pair.
    """

    __tablename__ = "interview_kits"
    __table_args__ = (
        UniqueConstraint("application_id", "round", "track",
                         name="uq_interview_kit_app_round_track"),
        Index("ix_interview_kits_application_id", "application_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Always "default" in phase 1; parallel tracks are phase 3. It is on the
    # unique constraint, so adding it later would rebuild that twice.
    track: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default",
    )
    questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    error: Mapped[str | None] = mapped_column(String)
    # ISO-8601 strings, matching the Pydantic schema these mirror.
    generated_at: Mapped[str | None] = mapped_column(String)
    generating_since: Mapped[str | None] = mapped_column(String)
    closed_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
