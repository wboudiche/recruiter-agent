from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ExperienceItem(BaseModel):
    title: str | None = None
    company: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None


class LinkItem(BaseModel):
    label: str
    url: str


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str | None
    email: str | None
    phone: str | None
    location: str | None
    headline: str | None
    summary: str | None
    skills: list[str]
    experience: list[ExperienceItem]
    education: list[EducationItem]
    links: list[LinkItem]
    source_type: str | None
    source_url: str | None
    resume_path: str | None
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CandidateCreateFromUrl(BaseModel):
    url: str


class CandidateCreateFromPaste(BaseModel):
    content: str
    source_url: str | None = None


class CandidateUpdate(BaseModel):
    # HttpUrl rejects non-http(s) schemes (javascript:, data:, file:) so the
    # value can never be a script-execution or local-file vector when rendered
    # as `<img src>`. max_length caps payload size before the DB layer.
    photo_url: HttpUrl | None = Field(default=None, max_length=2048)
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    headline: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=4096)

    @field_validator("photo_url")
    @classmethod
    def _len_cap(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is not None and len(str(v)) > 2048:
            raise ValueError("photo_url too long (max 2048 chars)")
        return v
