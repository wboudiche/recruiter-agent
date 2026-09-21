from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, JSON, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class JobStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String)
    criteria: Mapped[list[dict]] = mapped_column(JSON, default=list)
    interview_baseline: Mapped[list[dict] | None] = mapped_column(JSON)
    # The template preselected when a round starts. An archived template
    # is treated as no default. SET NULL keeps the job valid if a template
    # row is ever removed outright.
    default_interview_template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("interview_templates.id", ondelete="SET NULL"),
    )
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status", values_callable=lambda x: [e.value for e in x]),
        default=JobStatus.OPEN,
    )
    enrichment_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
