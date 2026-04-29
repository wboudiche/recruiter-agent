import pytest
from pydantic import ValidationError

from recruiter.schemas.extraction import ExtractedCandidate, ScoreResult
from recruiter.schemas.job import CriteriaItem, JobCreate


def test_job_create_requires_title_and_description() -> None:
    j = JobCreate(title="Backend", description="Build APIs", criteria=[])
    assert j.title == "Backend"

    with pytest.raises(ValidationError):
        JobCreate(title="", description="x", criteria=[])


def test_criteria_weight_in_range() -> None:
    CriteriaItem(name="Rust", weight=0.5, description="3+ yrs")
    with pytest.raises(ValidationError):
        CriteriaItem(name="Rust", weight=2.0, description="x")


def test_extracted_candidate_minimal() -> None:
    e = ExtractedCandidate(full_name="Alice", skills=["Python"])
    assert e.full_name == "Alice"


def test_score_result_validates_range() -> None:
    ScoreResult(score=80, breakdown=[], rationale="ok")
    with pytest.raises(ValidationError):
        ScoreResult(score=120, breakdown=[], rationale="x")
