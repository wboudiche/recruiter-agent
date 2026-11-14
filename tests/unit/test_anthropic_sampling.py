"""Claude 4.7 and later reject `temperature` with a 400, so the client sends it
only to the models that still accept it."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from recruiter.agent.types import ChatTurn
from recruiter.llm.anthropic import AnthropicLLMClient, accepts_temperature
from recruiter.llm.client import LLMMessage


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-sonnet-4-5",
    "claude-opus-4-1-20250805", "claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022",
])
def test_older_models_accept_temperature(model: str) -> None:
    assert accepts_temperature(model)


@pytest.mark.parametrize("model", [
    "claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-5-5", "claude-opus-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-haiku-5-5", "claude-fable-5-2",
    "claude-some-future-model",
])
def test_newer_and_unknown_models_do_not(model: str) -> None:
    assert not accepts_temperature(model)


def _text_response(text: str = '{"ok": true}') -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


@pytest.mark.asyncio
async def test_chat_omits_temperature_for_sonnet_5_5() -> None:
    client = AnthropicLLMClient(api_key="x", model="claude-sonnet-5-5")
    client._client.messages.create = AsyncMock(return_value=_text_response())
    await client.chat([LLMMessage(role="user", content="hi")], temperature=0.3)
    assert "temperature" not in client._client.messages.create.call_args.kwargs


@pytest.mark.asyncio
async def test_chat_with_tools_omits_temperature_for_sonnet_5_5() -> None:
    client = AnthropicLLMClient(api_key="x", model="claude-sonnet-5-5")
    client._client.messages.create = AsyncMock(return_value=_text_response())
    await client.chat_with_tools([ChatTurn(role="user", content="?")], [], temperature=0.7)
    assert "temperature" not in client._client.messages.create.call_args.kwargs
