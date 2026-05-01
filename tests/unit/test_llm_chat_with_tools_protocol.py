import pytest

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
from recruiter.llm.client import FakeLLMClient, LLMClient


@pytest.mark.asyncio
async def test_fake_llm_chat_with_tools_returns_queued_turn() -> None:
    fake = FakeLLMClient(
        tool_turn_responses=[
            AssistantTurn(text=None, tool_calls=[
                ToolCall(id="tc_1", name="get_candidate", arguments={}),
            ]),
            AssistantTurn(text="Marie has 8 years of Rust.", tool_calls=[]),
        ],
    )
    assert isinstance(fake, LLMClient)

    tools = [ToolDef(name="get_candidate", description="…", input_schema={"type": "object"})]
    history: list[ChatTurn] = [ChatTurn(role="user", content="tell me about her")]

    first = await fake.chat_with_tools(history, tools)
    assert first.text is None
    assert first.tool_calls[0].name == "get_candidate"

    second = await fake.chat_with_tools(history, tools)
    assert second.text == "Marie has 8 years of Rust."
    assert second.tool_calls == []


@pytest.mark.asyncio
async def test_fake_llm_chat_with_tools_exhausted_raises() -> None:
    fake = FakeLLMClient(tool_turn_responses=[])
    with pytest.raises(RuntimeError, match="exhausted"):
        await fake.chat_with_tools([], [])
