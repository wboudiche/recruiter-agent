import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
from recruiter.llm.client import LLMMessage

T = TypeVar("T", bound=BaseModel)


class OpenAICompatLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | httpx.MockTransport | None = None,
        timeout: float = 120.0,
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
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
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
            "temperature": 0.0,
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.input_schema,
                }} for t in tools
            ]
            body["tool_choice"] = "auto"

        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
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

    async def aclose(self) -> None:
        await self._client.aclose()


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
