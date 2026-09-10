from typing import Literal

from pydantic import BaseModel, Field, field_validator

Rating = Literal["strong", "adequate", "weak"]
KitStatus = Literal["generating", "ready", "error"]
QuestionSource = Literal["baseline", "probe"]


class _TextQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)
    criterion: str | None = Field(default=None, max_length=200)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question text cannot be blank")
        return v.strip()


class BaselineQuestion(_TextQuestion):
    """A question every candidate for this role is asked."""


class KitQuestion(_TextQuestion):
    source: QuestionSource
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None


class InterviewKit(BaseModel):
    status: KitStatus
    error: str | None = None
    generated_at: str | None = None
    submitted_at: str | None = None
    questions: list[KitQuestion] = Field(default_factory=list)
