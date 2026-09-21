from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from recruiter.schemas.interview import BaselineQuestion

# "score_gaps": today's generator, driven by criteria and the score
# breakdown. "none": curated questions only, no LLM call. Phase 4 adds a
# profile-driven mode for RH-style templates.
ProbeMode = Literal["score_gaps", "none"]

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
