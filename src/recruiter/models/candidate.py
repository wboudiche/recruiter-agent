from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class SourceType(str, Enum):
    URL = "url"
    RESUME = "resume"
    PASTE = "paste"


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(String)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience: Mapped[list[dict]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict]] = mapped_column(JSON, default=list)
    links: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_type: Mapped[SourceType | None] = mapped_column(SAEnum(SourceType, name="source_type"))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    resume_path: Mapped[str | None] = mapped_column(String(1024))
    raw_extracted: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
