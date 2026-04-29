import pytest

from recruiter.llm.anthropic import AnthropicLLMClient
from recruiter.llm.client import LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_chat_uses_anthropic_messages_create(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeMessage:
        def __init__(self) -> None:
            self.content = [type("B", (), {"text": "hello", "type": "text"})()]

    class FakeMessages:
        async def create(self, **kwargs: object) -> FakeMessage:
            captured.update(kwargs)
            return FakeMessage()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr("recruiter.llm.anthropic.AsyncAnthropic", FakeAsyncAnthropic)

    client = AnthropicLLMClient(api_key="test", model="claude-sonnet-4-6")
    out = await client.chat(messages=[LLMMessage(role="user", content="hi")], system="be helpful")
    assert out == "hello"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["system"] == "be helpful"


@pytest.mark.asyncio
async def test_chat_structured_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMessage:
        def __init__(self) -> None:
            self.content = [type("B", (), {"text": '{"full_name":"Alice","skills":["Python"]}', "type": "text"})()]

    class FakeMessages:
        async def create(self, **kwargs: object) -> FakeMessage:
            return FakeMessage()

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr("recruiter.llm.anthropic.AsyncAnthropic", FakeAsyncAnthropic)

    client = AnthropicLLMClient(api_key="test", model="claude-sonnet-4-6")
    result = await client.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert result.full_name == "Alice"
