from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class InterviewTemplate(Base):
    """An org-wide, reusable question set — "Technical", "RH screen".

    A round picks one when it starts; the kit snapshots it at creation
    (see interview_kits.template_snapshot), so editing a template never
    rewrites an existing kit. Archived rather than deleted, so kits and
    job defaults that point at it stay coherent.
    """

    __tablename__ = "interview_templates"
    __table_args__ = (
        # Unique among ACTIVE templates only, so an archived "RH screen"
        # does not block creating a new one with the same name.
        Index(
            "uq_interview_templates_active_name", "name",
            unique=True, postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    questions: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'"))
    probe_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="score_gaps", server_default="score_gaps",
    )
    include_job_questions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
