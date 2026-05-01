import json

import httpx
import pytest

from recruiter.agent.types import ChatTurn, ToolCall, ToolDef
from recruiter.llm.openai_compat import OpenAICompatLLMClient


def _ok_response(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body)


@pytest.mark.asyncio
async def test_chat_with_tools_text_only() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_response({
            "choices": [{"message": {"role": "assistant", "content": "hi", "tool_calls": None}}],
        })

    client = OpenAICompatLLMClient(
        base_url="https://x/v1", model="m", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    turn = await client.chat_with_tools(
        [ChatTurn(role="user", content="hi")],
        [ToolDef(name="get_candidate", description="d", input_schema={"type": "object"})],
        system="be helpful",
    )
    assert turn.text == "hi"
    assert turn.tool_calls == []
    assert captured["body"]["model"] == "m"
    assert captured["body"]["tools"] == [{
        "type": "function",
        "function": {"name": "get_candidate", "description": "d", "parameters": {"type": "object"}},
    }]
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "be helpful"}
    assert captured["body"]["messages"][1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_chat_with_tools_returns_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response({
            "choices": [{"message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "get_candidate", "arguments": "{}"},
                }],
            }}],
        })

    client = OpenAICompatLLMClient(
        base_url="https://x/v1", model="m", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    turn = await client.chat_with_tools(
        [ChatTurn(role="user", content="who is she")],
        [ToolDef(name="get_candidate", description="d", input_schema={"type": "object"})],
    )
    assert turn.text is None
    assert turn.tool_calls == [ToolCall(id="call_abc", name="get_candidate", arguments={})]


@pytest.mark.asyncio
async def test_chat_with_tools_serializes_history() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["msgs"] = json.loads(request.content)["messages"]
        return _ok_response({"choices": [{"message": {"content": "ok", "tool_calls": None}}]})

    client = OpenAICompatLLMClient(
        base_url="https://x/v1", model="m", api_key="k",
        transport=httpx.MockTransport(handler),
    )
    history = [
        ChatTurn(role="user", content="hi"),
        ChatTurn(role="assistant", content=None,
                 tool_calls=[ToolCall(id="c1", name="get_candidate", arguments={"x": 1})]),
        ChatTurn(role="tool", tool_call_id="c1", tool_name="get_candidate",
                 tool_result={"full_name": "Marie"}),
    ]
    await client.chat_with_tools(history, [])

    msgs = captured["msgs"]
    assert msgs[0] == {"role": "user", "content": "hi"}
    assert msgs[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "get_candidate", "arguments": '{"x": 1}'},
        }],
    }
    assert msgs[2] == {
        "role": "tool", "tool_call_id": "c1",
        "content": '{"full_name": "Marie"}',
    }
