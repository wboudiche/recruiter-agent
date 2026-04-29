from collections import deque
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

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


class FakeLLMClient:
    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        structured_responses: list[BaseModel] | None = None,
    ) -> None:
        self._text = deque(text_responses or [])
        self._structured = deque(structured_responses or [])
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
