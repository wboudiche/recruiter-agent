import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.extractor import extract_candidate
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_extract_candidate_calls_llm_with_text_and_returns_struct() -> None:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice Doe", email="alice@example.com", skills=["Python", "Rust"])
        ]
    )
    result = await extract_candidate(text="Alice Doe — alice@example.com — Python, Rust", llm=fake)
    assert result.full_name == "Alice Doe"
    assert "Rust" in result.skills

    sent = fake.calls[0]
    assert sent["kind"] == "structured"
    assert sent["schema"] == "ExtractedCandidate"
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Alice Doe" in user_msg.content


@pytest.mark.asyncio
async def test_extract_candidate_returns_empty_on_blank_text() -> None:
    fake = FakeLLMClient()
    result = await extract_candidate(text="", llm=fake)
    assert result.full_name is None
    assert result.skills == []
    assert fake.calls == []
