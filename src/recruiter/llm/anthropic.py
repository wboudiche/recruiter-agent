import json
import re
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
from recruiter.llm.client import EmptyLLMResponse, LLMMessage

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-6"

# Claude 4.7 and later answer a 400 to `temperature`. Matching the models that
# still accept it, rather than the ones that don't, keeps an unknown or future
# model on the side that works.
_SAMPLING_MODELS = re.compile(r"^claude-(3|(opus|sonnet|haiku)-4(-[0-6])?(-\d{8})?$)")


def accepts_temperature(model: str) -> bool:
    return bool(_SAMPLING_MODELS.match(model))


class AnthropicLLMClient:
    def __init__(self, *, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if accepts_temperature(self._model):
            kwargs["temperature"] = temperature
        if system is not None:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        text = "".join(parts)
        if not text.strip():
            # Same cause as the OpenAI-compatible path, different symptom: an
            # empty string here fails later as an opaque JSON validation error.
            stop = getattr(response, "stop_reason", None) or "unknown"
            raise EmptyLLMResponse(
                f"{self._model} returned no content (stop_reason={stop}). "
                f"Retry, or raise max_tokens (currently {max_tokens})."
            )
        return text

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
        api_messages = [_chat_turn_to_anthropic(m) for m in messages]
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }
        if accepts_temperature(self._model):
            kwargs["temperature"] = temperature
        if system is not None:
            kwargs["system"] = system
        if api_tools:
            kwargs["tools"] = api_tools

        resp = await self._client.messages.create(**kwargs)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
        text = "".join(text_parts) or None
        return AssistantTurn(text=text, tool_calls=tool_calls)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


def _chat_turn_to_anthropic(turn: ChatTurn) -> dict:
    if turn.role == "tool":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": turn.tool_call_id,
                "content": json.dumps(turn.tool_result or {}),
            }],
        }
    if turn.role == "assistant" and turn.tool_calls:
        blocks: list[dict] = []
        if turn.content:
            blocks.append({"type": "text", "text": turn.content})
        for tc in turn.tool_calls:
            blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return {"role": "assistant", "content": blocks}
    return {"role": turn.role, "content": turn.content or ""}
