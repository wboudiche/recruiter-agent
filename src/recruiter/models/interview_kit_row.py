from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
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
    # `t<template_id>` for a templated track, `default` without a template
    # (pipeline/kit_store.track_key); derived at creation, never changed.
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
    # Legacy single-submit timestamp, mirroring InterviewKit.submitted_at in
    # schemas/interview.py. Kept so the blob's contents survive the move,
    # even though per-interviewer submission now lives on the sheet.
    submitted_at: Mapped[str | None] = mapped_column(String)
    # Which template this kit was built from, if any. NULL for kits that
    # predate templates and for rounds started with "No template" — both
    # behave exactly as kits always have.
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("interview_templates.id", ondelete="SET NULL"),
    )
    # A copy of the name at creation, so "Round 2 · RH screen" stays
    # readable after the template is renamed or archived.
    template_name: Mapped[str | None] = mapped_column(String(128))
    # TemplateSnapshot as a dict. Regeneration reads this, never the live
    # template.
    template_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
