import asyncio
import json
import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
from recruiter.llm.client import LLMMessage

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# Statuses worth a second look. 429 is the common one on free-tier
# gateways (the shared upstream pool saturates and answers "temporarily
# rate-limited"); the 5xx family covers provider blips. Everything else
# — notably 401/402/404 — is definitive, and retrying only delays the
# error the user needs to see.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 4
_BASE_BACKOFF_S = 2.0
_MAX_BACKOFF_S = 30.0


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retry `attempt` (0-based).

    A `Retry-After` header is the provider telling us exactly when it
    will serve us again — prefer it over our own guess. Otherwise back
    off exponentially so a saturated pool isn't hammered at a fixed rate.
    """
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), _MAX_BACKOFF_S)
        except ValueError:
            pass  # HTTP-date form; fall through to the exponential guess.
    return min(_BASE_BACKOFF_S * (2 ** attempt), _MAX_BACKOFF_S)


class OpenAICompatLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
        # Sized for the slowest realistic backend, not the fastest: free
        # gateways serve big prompts an order of magnitude slower than a
        # paid API, and a premature ReadTimeout costs the whole extraction
        # (there is no resume — the pipeline restarts from the scrape).
        timeout: float = 300.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        body_messages = []
        if system is not None:
            body_messages.append({"role": "system", "content": system})
        body_messages.extend({"role": m.role, "content": m.content} for m in messages)
        body = {
            "model": self._model,
            "messages": body_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        response = await self._post(body, headers)
        if response.status_code >= 400:
            _raise_with_body(response)
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        json_schema = schema.model_json_schema()
        sys_combined = (system or "") + (
            "\n\nRespond ONLY with a single JSON object that matches this schema. "
            "No prose, no markdown fences.\n"
            f"Schema: {json.dumps(json_schema)}"
        )
        text = await self.chat(
            messages=messages,
            system=sys_combined.strip(),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return schema.model_validate_json(_strip_fences(text))

    async def chat_with_tools(
        self,
        messages: list[ChatTurn],
        tools: list[ToolDef],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AssistantTurn:
        body_messages: list[dict] = []
        if system is not None:
            body_messages.append({"role": "system", "content": system})
        for m in messages:
            body_messages.append(_chat_turn_to_openai(m))

        body: dict = {
            "model": self._model,
            "messages": body_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.input_schema,
                }} for t in tools
            ]
            body["tool_choice"] = "auto"

        response = await self._post(body, {"Authorization": f"Bearer {self._api_key}"})
        if response.status_code >= 400:
            _raise_with_body(response)
        msg = response.json()["choices"][0]["message"]

        raw_tcs = msg.get("tool_calls") or []
        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"] or "{}"),
            )
            for tc in raw_tcs
        ]
        return AssistantTurn(text=msg.get("content"), tool_calls=tool_calls)

    async def _post(self, body: dict, headers: dict) -> httpx.Response:
        """POST /chat/completions, retrying transient upstream failures.

        Returns the final response — the caller still decides what to do
        with a >=400 status, so a definitive error surfaces with its body
        intact rather than being masked by the retry loop.
        """
        url = f"{self._base_url}/chat/completions"
        for attempt in range(_MAX_ATTEMPTS):
            response = await self._client.post(url, json=body, headers=headers)
            last = attempt == _MAX_ATTEMPTS - 1
            if response.status_code not in _RETRY_STATUSES or last:
                return response
            delay = _retry_delay(response, attempt)
            logger.warning(
                "LLM HTTP %s from %s — retrying in %.1fs (attempt %d/%d)",
                response.status_code, url, delay, attempt + 1, _MAX_ATTEMPTS,
            )
            await asyncio.sleep(delay)
        return response  # unreachable; the loop always returns.

    async def aclose(self) -> None:
        await self._client.aclose()


def _raise_with_body(response: httpx.Response) -> None:
    body = response.text[:500]
    raise httpx.HTTPStatusError(
        f"LLM call failed: HTTP {response.status_code} from {response.request.url} — {body}",
        request=response.request,
        response=response,
    )


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _chat_turn_to_openai(turn: ChatTurn) -> dict:
    if turn.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": turn.tool_call_id,
            "content": json.dumps(turn.tool_result or {}),
        }
    if turn.role == "assistant" and turn.tool_calls:
        return {
            "role": "assistant",
            "content": turn.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in turn.tool_calls
            ],
        }
    return {"role": turn.role, "content": turn.content}
