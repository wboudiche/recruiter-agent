from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


def empty_sheet() -> dict:
    return {"answers": {}, "verdict": {"decision": None, "note": None}}


class InterviewAssignment(Base):
    """One interviewer on one application, with their feedback sheet.

    Questions are shared and live in `interview_kits`, one row per
    `(application_id, round, track)`; this assignment's sheet is matched to
    its kit by that triple. Only the answers, ratings and verdict are per
    person. Each interviewer writes their own row, so two people saving at
    once never overwrite each other.

    One row per interviewer PER ROUND. Reopening an application for a
    second interview creates a fresh set of rows at the next `round`,
    leaving the first round's submitted sheets immutable beside them —
    which is what makes a second interview possible without rejecting the
    candidate to get back through the funnel.
    """

    __tablename__ = "interview_assignments"
    __table_args__ = (
        # One track per interviewer per round (phase 3): a person sits on at
        # most one of a round's parallel interviews.
        UniqueConstraint("application_id", "user_id", "round",
                         name="uq_interview_assignment_app_user_round"),
        Index("ix_interview_assignments_application_id", "application_id"),
        Index("ix_interview_assignments_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    # Which interview round this sheet belongs to; matches
    # `applications.interview_round` for the round currently in progress.
    round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    # Which track within the round — the kit this sheet's answers are keyed
    # against. At most one per person per round (see the constraint above).
    track: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default",
    )
    sheet: Mapped[dict] = mapped_column(JSON, nullable=False, default=empty_sheet)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
