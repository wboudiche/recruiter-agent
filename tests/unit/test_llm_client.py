import pytest

from recruiter.llm.client import FakeLLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_fake_chat_returns_canned_response() -> None:
    fake = FakeLLMClient(text_responses=["hello"])
    out = await fake.chat(messages=[LLMMessage(role="user", content="hi")])
    assert out == "hello"


@pytest.mark.asyncio
async def test_fake_structured_returns_typed_response() -> None:
    expected = ExtractedCandidate(full_name="Alice", skills=["Python"])
    fake = FakeLLMClient(structured_responses=[expected])
    out = await fake.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert out.full_name == "Alice"


@pytest.mark.asyncio
async def test_fake_raises_when_responses_exhausted() -> None:
    fake = FakeLLMClient(text_responses=[])
    with pytest.raises(RuntimeError, match="exhausted"):
        await fake.chat(messages=[LLMMessage(role="user", content="hi")])
