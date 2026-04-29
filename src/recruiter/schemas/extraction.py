from pydantic import BaseModel, Field

from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem


class ExtractedCandidate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)


class ScoreBreakdownItem(BaseModel):
    criterion: str
    weight: float = Field(ge=0.0, le=1.0)
    score: int = Field(ge=0, le=100)
    rationale: str


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    breakdown: list[ScoreBreakdownItem]
    rationale: str
