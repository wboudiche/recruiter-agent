# tests/unit/test_criteria_suggester.py
import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.criteria_suggester import suggest_criteria
from recruiter.schemas.job_suggest import SuggestedCriteria, SuggestedCriterion


def _resp(items: list[tuple[str, float, str]]) -> SuggestedCriteria:
    return SuggestedCriteria(
        criteria=[SuggestedCriterion(name=n, weight=w, description=d) for n, w, d in items],
    )


@pytest.mark.asyncio
async def test_passes_through_a_well_formed_response() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([
            ("Java expertise", 0.40, "5+ years professional Java"),
            ("Spring framework", 0.30, "Production Spring Boot"),
            ("System design", 0.20, "Designed distributed services"),
            ("Communication", 0.10, "Clear written/verbal communication"),
        ]),
    ])
    out = await suggest_criteria(
        title="Senior Java Developer",
        description="We are looking for a Senior Java Developer with strong Spring experience...",
        llm=fake,
    )
    assert len(out) == 4
    assert out[0].name == "Java expertise"
    assert sum(c.weight for c in out) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_normalizes_weights_to_sum_one() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 0.30, "x"), ("B", 0.30, "x"), ("C", 0.30, "x"), ("D", 0.30, "x")]),
    ])
    out = await suggest_criteria(
        title=None,
        description="x" * 60,
        llm=fake,
    )
    total = sum(c.weight for c in out)
    assert total == pytest.approx(1.0)
    # Residual must land on the largest weight after rounding.
    assert all(0.0 <= c.weight <= 1.0 for c in out)


@pytest.mark.asyncio
async def test_reprompts_once_when_count_below_three() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),  # 2 — too few
        _resp([("A", 0.4, "x"), ("B", 0.3, "y"), ("C", 0.3, "z")]),  # valid
    ])
    out = await suggest_criteria(title="t", description="x" * 60, llm=fake)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_raises_when_count_off_after_reprompt() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),
        _resp([("A", 1.0, "x"), ("B", 0.0, "y")]),
    ])
    with pytest.raises(ValueError):
        await suggest_criteria(title="t", description="x" * 60, llm=fake)


@pytest.mark.asyncio
async def test_prompt_includes_title_and_description() -> None:
    fake = FakeLLMClient(structured_responses=[
        _resp([("A", 0.5, "x"), ("B", 0.3, "y"), ("C", 0.2, "z")]),
    ])
    await suggest_criteria(
        title="Backend Engineer",
        description="Build Rust APIs. " * 5,
        llm=fake,
    )
    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Backend Engineer" in user_msg.content
    assert "Build Rust APIs" in user_msg.content
