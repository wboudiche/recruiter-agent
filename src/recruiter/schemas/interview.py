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
    # Legacy: answers and ratings now live on each interviewer's sheet
    # (InterviewSheet). These two are read for kits recorded before that
    # change and never written again.
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None
    # User id of the interviewer who appended the question; None for
    # generated and recruiter-authored questions.
    added_by: int | None = None


class InterviewKit(BaseModel):
    status: KitStatus
    error: str | None = None
    generated_at: str | None = None
    # Legacy single-submit timestamp; see KitQuestion.answer.
    submitted_at: str | None = None
    # Set when the candidate moves to INTERVIEWED, by the all-sheets-in
    # rule or the recruiter's manual move.
    closed_at: str | None = None
    questions: list[KitQuestion] = Field(default_factory=list)


class GeneratedQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    criterion: str | None = Field(default=None, max_length=200)


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list)


VerdictDecision = Literal["hire", "no_hire", "unsure"]


class SheetAnswer(BaseModel):
    answer: str | None = Field(default=None, max_length=20000)
    rating: Rating | None = None


class Verdict(BaseModel):
    decision: VerdictDecision | None = None
    note: str | None = Field(default=None, max_length=2000)


class InterviewSheet(BaseModel):
    """One interviewer's feedback over the shared kit, keyed by question id."""

    answers: dict[str, SheetAnswer] = Field(default_factory=dict)
    verdict: Verdict = Field(default_factory=Verdict)


class SheetRead(BaseModel):
    user_id: int
    name: str | None
    email: str
    sheet: InterviewSheet
    submitted_at: str | None
