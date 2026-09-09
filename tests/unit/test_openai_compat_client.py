import json

import httpx
import pytest

from recruiter.llm.client import LLMMessage
from recruiter.llm.openai_compat import OpenAICompatLLMClient
from recruiter.schemas.extraction import ExtractedCandidate


@pytest.mark.asyncio
async def test_chat_calls_chat_completions_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        body = {"choices": [{"message": {"content": "hello"}}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = OpenAICompatLLMClient(
        base_url="http://localhost:8001/v1",
        model="gpt-oss-120b",
        api_key="not-needed",
        transport=transport,
    )
    out = await client.chat(messages=[LLMMessage(role="user", content="hi")], system="be helpful")
    assert out == "hello"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["model"] == "gpt-oss-120b"
    assert captured["body"]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_chat_structured_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": '{"full_name":"Alice","skills":["Python"]}'}}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = OpenAICompatLLMClient(
        base_url="http://localhost:8001/v1",
        model="gpt-oss-120b",
        api_key="x",
        transport=transport,
    )
    result = await client.chat_structured(
        messages=[LLMMessage(role="user", content="extract")],
        schema=ExtractedCandidate,
    )
    assert result.full_name == "Alice"


# --- empty / null content ------------------------------------------------
# A reasoning model's reasoning tokens count against max_tokens. When they
# exhaust the budget the provider answers 200 with `content: null` and
# finish_reason "length". Returned unchecked that None travelled until it hit
# .strip() inside _strip_fences, surfacing as
# `AttributeError: 'NoneType' object has no attribute 'strip'` — a 502 with
# nothing in it to act on.


def _client(handler) -> OpenAICompatLLMClient:
    return OpenAICompatLLMClient(
        base_url="http://localhost:8001/v1",
        model="gpt-oss-120b",
        api_key="not-needed",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_chat_raises_a_named_error_when_content_is_null() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            "usage": {"completion_tokens": 512,
                      "completion_tokens_details": {"reasoning_tokens": 512}},
        })

    from recruiter.llm.client import EmptyLLMResponse

    with pytest.raises(EmptyLLMResponse) as ei:
        await _client(handler).chat(messages=[LLMMessage(role="user", content="hi")])

    msg = str(ei.value)
    # The message has to name the cause and the lever, or it is no better than
    # the AttributeError it replaces.
    assert "length" in msg
    assert "max_tokens" in msg
    assert "reasoning" in msg.lower()


@pytest.mark.asyncio
async def test_chat_raises_when_content_is_empty_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "   "}, "finish_reason": "stop"}],
        })

    from recruiter.llm.client import EmptyLLMResponse

    with pytest.raises(EmptyLLMResponse):
        await _client(handler).chat(messages=[LLMMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_chat_structured_surfaces_the_same_error() -> None:
    """The structured path is where this actually bit: query suggestion."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
        })

    from recruiter.llm.client import EmptyLLMResponse
    from recruiter.schemas.job_suggest import SuggestedSearchQuery

    with pytest.raises(EmptyLLMResponse):
        await _client(handler).chat_structured(
            messages=[LLMMessage(role="user", content="hi")],
            schema=SuggestedSearchQuery,
        )
