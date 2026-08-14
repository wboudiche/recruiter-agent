"""Retry behaviour for transient LLM failures.

Free-tier gateways (OpenRouter via the LINAGORA proxy, in practice)
answer 429 whenever the shared pool is saturated. Without a retry the
pipeline strands the application on EXTRACTING — one throttle and the
candidate never scores. These tests pin the backoff contract.
"""

import httpx
import pytest

from recruiter.agent.types import ChatTurn, ToolDef
from recruiter.llm import openai_compat
from recruiter.llm.client import LLMMessage
from recruiter.llm.openai_compat import OpenAICompatLLMClient


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """Collect the backoff delays instead of waiting them out."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(openai_compat.asyncio, "sleep", fake_sleep)
    return slept


def _client(handler) -> OpenAICompatLLMClient:
    return OpenAICompatLLMClient(
        base_url="https://x/v1", model="m", api_key="k",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_chat_retries_429_then_succeeds(_no_real_sleeping) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"message": "rate-limited upstream"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    out = await _client(handler).chat([LLMMessage(role="user", content="hi")])

    assert out == "OK"
    assert len(calls) == 3
    # Backoff must grow, not hammer the throttled provider at a fixed rate.
    assert _no_real_sleeping == sorted(_no_real_sleeping)
    assert _no_real_sleeping[0] > 0


@pytest.mark.asyncio
async def test_chat_honours_retry_after_header(_no_real_sleeping) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    await _client(handler).chat([LLMMessage(role="user", content="hi")])

    assert _no_real_sleeping == [7.0]


@pytest.mark.asyncio
async def test_chat_gives_up_and_reports_the_last_body(_no_real_sleeping) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "still rate-limited"}})

    with pytest.raises(httpx.HTTPStatusError, match="still rate-limited"):
        await _client(handler).chat([LLMMessage(role="user", content="hi")])

    # Bounded: it must stop rather than retry forever.
    assert 1 < len(calls) <= openai_compat._MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_auth_errors_are_not_retried(_no_real_sleeping) -> None:
    """A 401 is definitive — retrying burns time and changes nothing."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"detail": "token invalid"})

    with pytest.raises(httpx.HTTPStatusError, match="token invalid"):
        await _client(handler).chat([LLMMessage(role="user", content="hi")])

    assert len(calls) == 1
    assert _no_real_sleeping == []


def test_default_timeout_fits_a_slow_free_tier_model() -> None:
    """Free-tier models are slow: a 6.6k-char profile measured 80s on
    `gpt-oss-20b:free`, and exceeded the old 120s budget under load —
    surfacing as a bare ReadTimeout with the card stuck on EXTRACTING.
    The default must leave room for that, not just for a fast paid API."""
    client = OpenAICompatLLMClient(base_url="https://x/v1", model="m", api_key="k")

    assert client._client.timeout.read >= 300.0


@pytest.mark.asyncio
async def test_chat_with_tools_retries_too(_no_real_sleeping) -> None:
    """The agent loop hits the same throttle as extraction."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hi", "tool_calls": None}}],
        })

    turn = await _client(handler).chat_with_tools(
        [ChatTurn(role="user", content="hi")],
        [ToolDef(name="t", description="d", input_schema={"type": "object"})],
    )

    assert turn.text == "hi"
    assert len(calls) == 2
