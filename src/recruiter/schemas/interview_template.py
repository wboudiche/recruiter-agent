from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recruiter.schemas.interview import BaselineQuestion

# "score_gaps": the technical generator, driven by criteria and the score
# breakdown. "profile": built from the candidate's own history and what
# enrichment found, for RH-style rounds, and blind to the scoring.
# "none": curated questions only, no LLM call.
ProbeMode = Literal["score_gaps", "profile", "none"]

# A template question is snapshotted into a kit as `t<template_id>-<id>`,
# and KitQuestion.id is capped at 64. Capping the template side here keeps
# every namespaced id inside that limit. Editor-minted UUIDs are 36.
TEMPLATE_QUESTION_ID_MAX = 48


class TemplateQuestion(BaselineQuestion):
    id: str = Field(min_length=1, max_length=TEMPLATE_QUESTION_ID_MAX)


class InterviewTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    questions: list[TemplateQuestion] = Field(default_factory=list)
    probe_mode: ProbeMode = "score_gaps"
    include_job_questions: bool = True


class InterviewTemplateUpdate(BaseModel):
    """Every field optional. Which ones the caller actually sent is read
    from `model_fields_set`, so `description: null` clears the description
    while an absent field leaves it alone."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    questions: list[TemplateQuestion] | None = None
    probe_mode: ProbeMode | None = None
    include_job_questions: bool | None = None
    is_active: bool | None = None


class InterviewTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    questions: list[TemplateQuestion]
    probe_mode: ProbeMode
    include_job_questions: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TemplateSnapshot(BaseModel):
    """What a kit was built from, frozen when the kit was created.

    Regeneration reads this, never the live template, so editing a
    template cannot rewrite a round already under way. `questions` are
    already namespaced (see `snapshot_of`).
    """

    questions: list[BaselineQuestion] = Field(default_factory=list)
    probe_mode: ProbeMode
    include_job_questions: bool


# What kind of interview a template runs, as the editor names it. The
# backend stores probe_mode/include_job_questions; the kind only steers how
# suggested questions are written.
TemplateKind = Literal["technical", "hr", "custom"]


class SuggestedTemplateQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    criterion: str | None = Field(default=None, max_length=200)


class SuggestedTemplateQuestions(BaseModel):
    questions: list[SuggestedTemplateQuestion]


EXISTING_MAX = 50
EXISTING_ITEM_MAX = 2000


class SuggestTemplateQuestionsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    kind: TemplateKind
    job_id: int | None = None
    existing: list[str] = Field(default_factory=list)

    @field_validator("existing", mode="before")
    @classmethod
    def _trim_existing(cls, value: object) -> object:
        """Trimmed, never refused: the editor has no cap on how many
        questions a template holds, and refusing would make every later click
        fail. The most recent 50 are what a repeat is most likely of."""
        if not isinstance(value, list):
            return value
        return [v[:EXISTING_ITEM_MAX] if isinstance(v, str) else v
                for v in value[-EXISTING_MAX:]]
