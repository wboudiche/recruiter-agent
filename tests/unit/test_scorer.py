import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.scorer import score_candidate
from recruiter.schemas.candidate import ExperienceItem
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult
from recruiter.schemas.job import CriteriaItem


@pytest.mark.asyncio
async def test_score_candidate_calls_llm_with_jd_criteria_and_candidate() -> None:
    candidate = ExtractedCandidate(
        full_name="Alice",
        skills=["Python", "Rust"],
        experience=[ExperienceItem(title="Senior Backend", company="Acme", start="2020", end="2024")],
    )
    criteria = [CriteriaItem(name="Rust", weight=0.6, description="2+ years"), CriteriaItem(name="APIs", weight=0.4, description="REST/gRPC")]
    expected = ScoreResult(
        score=82,
        breakdown=[
            ScoreBreakdownItem(criterion="Rust", weight=0.6, score=80, rationale="Strong Rust signal"),
            ScoreBreakdownItem(criterion="APIs", weight=0.4, score=85, rationale="Backend exp"),
        ],
        rationale="Solid backend with Rust",
    )
    fake = FakeLLMClient(structured_responses=[expected])

    result = await score_candidate(
        job_title="Backend Engineer",
        job_description="Build Rust APIs",
        criteria=criteria,
        candidate=candidate,
        llm=fake,
    )
    assert result.score == 82
    assert len(result.breakdown) == 2

    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Backend Engineer" in user_msg.content
    assert "Rust" in user_msg.content
    assert "Alice" in user_msg.content
