from collections import deque
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolDef

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


@runtime_checkable
class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str: ...

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T: ...

    async def chat_with_tools(
        self,
        messages: list[ChatTurn],
        tools: list[ToolDef],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AssistantTurn: ...


class EmptyLLMResponse(RuntimeError):
    """The provider answered successfully but carried no usable text.

    Distinct from an HTTP failure: the call was accepted and billed, the model
    simply produced nothing to parse. The usual cause is a reasoning model
    whose reasoning tokens count against `max_tokens` — when they exhaust the
    budget the message comes back with null content and finish_reason
    "length". Raised rather than returned so the None cannot travel: it used
    to surface far away as `AttributeError: 'NoneType' object has no attribute
    'strip'`, which told the user nothing.
    """


class FakeLLMClient:
    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        structured_responses: list[BaseModel] | None = None,
        tool_turn_responses: list[AssistantTurn] | None = None,
    ) -> None:
        self._text = deque(text_responses or [])
        self._structured = deque(structured_responses or [])
        self._tool_turns = deque(tool_turn_responses or [])
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append({
            "kind": "chat", "messages": messages, "system": system,
            "max_tokens": max_tokens, "temperature": temperature,
        })
        if not self._text:
            raise RuntimeError("FakeLLMClient text_responses exhausted")
        return self._text.popleft()

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> T:
        self.calls.append({
            "kind": "structured", "messages": messages, "system": system,
            "schema": schema.__name__, "max_tokens": max_tokens, "temperature": temperature,
        })
        if not self._structured:
            raise RuntimeError("FakeLLMClient structured_responses exhausted")
        nxt = self._structured.popleft()
        if not isinstance(nxt, schema):
            raise TypeError(f"FakeLLMClient queued response is {type(nxt).__name__}, expected {schema.__name__}")
        return nxt

    async def chat_with_tools(
        self,
        messages: list[ChatTurn],
        tools: list[ToolDef],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AssistantTurn:
        self.calls.append({
            "kind": "tools", "messages": messages, "tools": tools,
            "system": system, "max_tokens": max_tokens, "temperature": temperature,
        })
        if not self._tool_turns:
            raise RuntimeError("FakeLLMClient tool_turn_responses exhausted")
        return self._tool_turns.popleft()
