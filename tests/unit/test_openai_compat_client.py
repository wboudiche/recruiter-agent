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
