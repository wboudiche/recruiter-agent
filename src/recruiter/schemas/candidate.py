from datetime import datetime

from pydantic import BaseModel


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
    created_at: datetime
    updated_at: datetime


class CandidateCreateFromUrl(BaseModel):
    url: str


class CandidateCreateFromPaste(BaseModel):
    content: str
    source_url: str | None = None
