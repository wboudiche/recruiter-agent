# src/recruiter/schemas/job_suggest.py
from pydantic import BaseModel, Field

from recruiter.schemas.job import CriteriaItem


class SuggestCriteriaRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=50)


class SuggestCriteriaResponse(BaseModel):
    criteria: list[CriteriaItem]


# Internal LLM-output schema. Lives next to its consumer; not re-exported.
class SuggestedCriterion(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)


class SuggestedCriteria(BaseModel):
    criteria: list[SuggestedCriterion]


class SuggestSearchQueryRequest(BaseModel):
    sources: list[str] = Field(min_length=1)


class SuggestSearchQueryResponse(BaseModel):
    query: str


# Internal LLM-output schema.
class SuggestedSearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=512)
