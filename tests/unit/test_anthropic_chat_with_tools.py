from unittest.mock import AsyncMock, MagicMock

import pytest

from recruiter.agent.types import ChatTurn, ToolCall, ToolDef
from recruiter.llm.anthropic import AnthropicLLMClient


def _block(type_: str, **kwargs):
    block = MagicMock()
    block.type = type_
    for k, v in kwargs.items():
        setattr(block, k, v)
    return block


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_text_only(monkeypatch) -> None:
    response = MagicMock()
    response.content = [_block("text", text="Marie has 8 years.")]
    response.stop_reason = "end_turn"

    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    turn = await client.chat_with_tools(
        [ChatTurn(role="user", content="hi")],
        [ToolDef(name="get_candidate", description="d", input_schema={"type": "object"})],
        system="be brief",
    )
    assert turn.text == "Marie has 8 years."
    assert turn.tool_calls == []

    kwargs = client._client.messages.create.call_args.kwargs
    assert kwargs["system"] == "be brief"
    assert kwargs["tools"] == [{
        "name": "get_candidate", "description": "d", "input_schema": {"type": "object"},
    }]


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_returns_tool_use() -> None:
    response = MagicMock()
    response.content = [
        _block("text", text="Let me check."),
        _block("tool_use", id="toolu_1", name="get_candidate", input={"q": "x"}),
    ]
    response.stop_reason = "tool_use"

    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    turn = await client.chat_with_tools([ChatTurn(role="user", content="?")], [])
    assert turn.text == "Let me check."
    assert turn.tool_calls == [ToolCall(id="toolu_1", name="get_candidate", arguments={"q": "x"})]


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_serializes_history() -> None:
    response = MagicMock()
    response.content = [_block("text", text="ok")]
    response.stop_reason = "end_turn"
    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    history = [
        ChatTurn(role="user", content="hi"),
        ChatTurn(role="assistant", content="thinking",
                 tool_calls=[ToolCall(id="t1", name="get_candidate", arguments={})]),
        ChatTurn(role="tool", tool_call_id="t1", tool_name="get_candidate",
                 tool_result={"full_name": "Marie"}),
    ]
    await client.chat_with_tools(history, [])
    msgs = client._client.messages.create.call_args.kwargs["messages"]
    assert msgs[0] == {"role": "user", "content": "hi"}
    assert msgs[1]["role"] == "assistant"
    assert any(b["type"] == "tool_use" and b["id"] == "t1" for b in msgs[1]["content"])
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "t1",
        "content": '{"full_name": "Marie"}',
    }
