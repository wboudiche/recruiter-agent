# Plan D — Per-application chat panel implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a right-side chat panel on the application detail page that lets the recruiter ask grounded questions about a candidate and reversibly validate/reject through audited tool calls, backed by a provider-agnostic `LLMClient.chat_with_tools` abstraction.

**Architecture:** Stateless `agent/chat.py` loop that loads `ChatMessage` history, calls `chat_with_tools`, executes tool handlers, and streams NDJSON events over a single POST. Tools are pure functions taking `(session, application_id, args)`. Frontend `useChat` parses NDJSON via `ReadableStream`, renders user/assistant/tool/action cards in `ChatPanel`. State changes get an in-memory undo token (15-min TTL).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + asyncpg + Alembic + PostgreSQL + Pydantic v2 (backend); React + TanStack Query + TypeScript + Vitest + RTL + MSW (frontend); httpx.MockTransport for OpenAI-compat tests; testcontainers for Postgres.

**Reference spec:** `docs/superpowers/specs/2026-05-01-plan-d-chat-panel-design.md`

---

## File structure

**Backend (new):**
- `src/recruiter/models/chat_message.py` — `ChatMessage` ORM + `MessageRole` enum
- `src/recruiter/agent/__init__.py` — package marker
- `src/recruiter/agent/types.py` — `ChatTurn`, `ToolDef`, `ToolCall`, `AssistantTurn` dataclasses
- `src/recruiter/agent/tools.py` — 8 tool handlers + `TOOLS` registry (JSON Schema)
- `src/recruiter/agent/undo.py` — in-memory undo-token store
- `src/recruiter/agent/events.py` — NDJSON event constants + serializer
- `src/recruiter/agent/chat.py` — `run_turn` agent loop (async generator of events)
- `src/recruiter/api/chat.py` — POST stream / GET history / POST undo
- `src/recruiter/schemas/chat.py` — `ChatMessageRead`, `ChatRequest`, `UndoRequest`
- `alembic/versions/<rev>_chat_messages.py` — table + index migration

**Backend (modified):**
- `src/recruiter/llm/client.py` — add `chat_with_tools` to Protocol; extend `FakeLLMClient`
- `src/recruiter/llm/openai_compat.py` — implement `chat_with_tools`
- `src/recruiter/llm/anthropic.py` — implement `chat_with_tools`
- `src/recruiter/models/__init__.py` — export new symbols
- `src/recruiter/main.py` — mount `chat.router`

**Frontend (new):**
- `recruiter-frontend/src/lib/ndjson.ts` — NDJSON `ReadableStream` parser
- `recruiter-frontend/src/lib/ndjson.test.ts`
- `recruiter-frontend/src/hooks/use-chat.ts` — history query + sendMessage + undo
- `recruiter-frontend/src/hooks/use-chat.test.tsx`
- `recruiter-frontend/src/components/applications/chat-panel.tsx`
- `recruiter-frontend/src/components/applications/chat-panel.test.tsx`

**Frontend (modified):**
- `recruiter-frontend/src/routes/application-detail.tsx` — replace the "Chat panel coming in Plan D" placeholder with `<ChatPanel />`
- `recruiter-frontend/src/lib/query-keys.ts` — add `chat(id)` key
- `recruiter-frontend/SMOKE.md` — append Plan D smoke checklist

**Tests (new):**
- `tests/unit/test_chat_message_model.py`
- `tests/unit/test_llm_chat_with_tools_protocol.py`
- `tests/unit/test_openai_compat_chat_with_tools.py`
- `tests/unit/test_anthropic_chat_with_tools.py`
- `tests/unit/test_agent_tools.py`
- `tests/unit/test_agent_undo.py`
- `tests/unit/test_agent_events.py`
- `tests/unit/test_agent_chat_loop.py`
- `tests/api/test_chat_api.py`

---

## Task 1: `ChatMessage` model + migration

**Files:**
- Create: `src/recruiter/models/chat_message.py`
- Create: `tests/unit/test_chat_message_model.py`
- Modify: `src/recruiter/models/__init__.py`
- Create: `alembic/versions/<auto>_chat_messages.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_chat_message_model.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import Application, Candidate, ChatMessage, Job, MessageRole, Stage


@pytest.mark.asyncio
async def test_chat_message_roundtrip(db_session_with_schema: AsyncSession) -> None:
    job = Job(title="Backend", description="Build APIs", criteria=[])
    db_session_with_schema.add(job)
    await db_session_with_schema.flush()
    candidate = Candidate(source_type="paste")
    db_session_with_schema.add(candidate)
    await db_session_with_schema.flush()
    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED)
    db_session_with_schema.add(app)
    await db_session_with_schema.flush()

    user_msg = ChatMessage(application_id=app.id, role=MessageRole.USER, content="hi")
    assistant_msg = ChatMessage(
        application_id=app.id,
        role=MessageRole.ASSISTANT,
        content=None,
        tool_calls=[{"id": "tc_1", "name": "get_candidate", "arguments": {}}],
    )
    tool_msg = ChatMessage(
        application_id=app.id,
        role=MessageRole.TOOL,
        tool_call_id="tc_1",
        tool_name="get_candidate",
        tool_result={"full_name": "Marie"},
    )
    db_session_with_schema.add_all([user_msg, assistant_msg, tool_msg])
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        ChatMessage.__table__.select().order_by(ChatMessage.id)
    )).all()
    assert len(fetched) == 3
    assert fetched[0].role == "user"
    assert fetched[1].tool_calls == [{"id": "tc_1", "name": "get_candidate", "arguments": {}}]
    assert fetched[2].tool_result == {"full_name": "Marie"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_chat_message_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChatMessage' from 'recruiter.models'`

- [ ] **Step 3: Create the model**

`src/recruiter/models/chat_message.py`:

```python
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_app_created", "application_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="chat_message_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(String)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(64))
    tool_result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Export from models package**

Edit `src/recruiter/models/__init__.py` — add the imports and `__all__` entries:

```python
from recruiter.models.chat_message import ChatMessage, MessageRole
```

Add `"ChatMessage"` and `"MessageRole"` to `__all__`.

- [ ] **Step 5: Generate the Alembic migration**

Run: `.venv/bin/alembic revision --autogenerate -m "chat_messages table"`

Open the generated file in `alembic/versions/` and verify the `upgrade()` body matches:

```python
def upgrade() -> None:
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.Enum('user', 'assistant', 'tool', name='chat_message_role'), nullable=False),
        sa.Column('content', sa.String(), nullable=True),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('tool_call_id', sa.String(length=64), nullable=True),
        sa.Column('tool_name', sa.String(length=64), nullable=True),
        sa.Column('tool_result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_messages_app_created', 'chat_messages', ['application_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_chat_messages_app_created', table_name='chat_messages')
    op.drop_table('chat_messages')
    sa.Enum(name='chat_message_role').drop(op.get_bind(), checkfirst=True)
```

If autogenerate produced something different, edit it to match (especially the explicit enum drop in `downgrade`).

- [ ] **Step 6: Apply the migration to local Postgres**

Run: `.venv/bin/alembic upgrade head`
Expected: `Running upgrade ... -> <new rev>, chat_messages table`

- [ ] **Step 7: Run the test, verify it passes**

Run: `.venv/bin/pytest tests/unit/test_chat_message_model.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/recruiter/models/chat_message.py src/recruiter/models/__init__.py \
  alembic/versions/*chat_messages.py tests/unit/test_chat_message_model.py
git commit -m "feat(chat): add ChatMessage model + migration"
```

---

## Task 2: `chat_with_tools` Protocol + dataclasses + FakeLLMClient

**Files:**
- Create: `src/recruiter/agent/__init__.py`
- Create: `src/recruiter/agent/types.py`
- Create: `tests/unit/test_llm_chat_with_tools_protocol.py`
- Modify: `src/recruiter/llm/client.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_llm_chat_with_tools_protocol.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_llm_chat_with_tools_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recruiter.agent'`

- [ ] **Step 3: Create the agent package + types**

`src/recruiter/agent/__init__.py`:

```python
```

`src/recruiter/agent/types.py`:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict  # JSON Schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AssistantTurn:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ChatTurn:
    """One row of conversation history fed to chat_with_tools.

    role='user' | 'assistant' | 'tool'.
    For assistant turns with tool calls, content may be None and tool_calls is non-empty.
    For tool result turns, tool_call_id, tool_name, and tool_result must all be set.
    """
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
```

- [ ] **Step 4: Extend `LLMClient` Protocol + `FakeLLMClient`**

Edit `src/recruiter/llm/client.py`:

```python
from collections import deque
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from recruiter.agent.types import AssistantTurn, ChatTurn, ToolDef

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: str
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
    ) -> AssistantTurn: ...


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

    async def chat(self, messages, *, system=None, max_tokens=2048, temperature=0.0):
        self.calls.append({"kind": "chat", "messages": messages, "system": system,
                           "max_tokens": max_tokens, "temperature": temperature})
        if not self._text:
            raise RuntimeError("FakeLLMClient text_responses exhausted")
        return self._text.popleft()

    async def chat_structured(self, messages, *, schema, system=None, max_tokens=2048, temperature=0.0):
        self.calls.append({"kind": "structured", "messages": messages, "system": system,
                           "schema": schema.__name__, "max_tokens": max_tokens, "temperature": temperature})
        if not self._structured:
            raise RuntimeError("FakeLLMClient structured_responses exhausted")
        nxt = self._structured.popleft()
        if not isinstance(nxt, schema):
            raise TypeError(f"FakeLLMClient queued response is {type(nxt).__name__}, expected {schema.__name__}")
        return nxt

    async def chat_with_tools(self, messages, tools, *, system=None, max_tokens=2048):
        self.calls.append({"kind": "tools", "messages": messages, "tools": tools,
                           "system": system, "max_tokens": max_tokens})
        if not self._tool_turns:
            raise RuntimeError("FakeLLMClient tool_turn_responses exhausted")
        return self._tool_turns.popleft()
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_llm_chat_with_tools_protocol.py tests/unit/test_llm_client.py -v`
Expected: PASS for both files (existing `test_llm_client` should still pass — backward compatible).

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/agent/__init__.py src/recruiter/agent/types.py \
  src/recruiter/llm/client.py tests/unit/test_llm_chat_with_tools_protocol.py
git commit -m "feat(llm): add chat_with_tools to LLMClient protocol + FakeLLMClient"
```

---

## Task 3: `OpenAICompatLLMClient.chat_with_tools`

**Files:**
- Create: `tests/unit/test_openai_compat_chat_with_tools.py`
- Modify: `src/recruiter/llm/openai_compat.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_openai_compat_chat_with_tools.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_openai_compat_chat_with_tools.py -v`
Expected: FAIL — `AttributeError: 'OpenAICompatLLMClient' object has no attribute 'chat_with_tools'`

- [ ] **Step 3: Implement `chat_with_tools` on `OpenAICompatLLMClient`**

Add to `src/recruiter/llm/openai_compat.py` (inside the class, after `chat_structured`):

```python
async def chat_with_tools(
    self,
    messages: "list[ChatTurn]",
    tools: "list[ToolDef]",
    *,
    system: str | None = None,
    max_tokens: int = 2048,
) -> "AssistantTurn":
    body_messages: list[dict] = []
    if system is not None:
        body_messages.append({"role": "system", "content": system})
    for m in messages:
        body_messages.append(_chat_turn_to_openai(m))

    body = {
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
```

Add this module-level helper at the bottom:

```python
def _chat_turn_to_openai(turn: "ChatTurn") -> dict:
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
```

And add the imports at the top:

```python
from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_openai_compat_chat_with_tools.py tests/unit/test_openai_compat_client.py -v`
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/llm/openai_compat.py tests/unit/test_openai_compat_chat_with_tools.py
git commit -m "feat(llm): implement chat_with_tools for OpenAI-compat client"
```

---

## Task 4: `AnthropicLLMClient.chat_with_tools`

**Files:**
- Create: `tests/unit/test_anthropic_chat_with_tools.py`
- Modify: `src/recruiter/llm/anthropic.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_anthropic_chat_with_tools.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from recruiter.agent.types import ChatTurn, ToolCall, ToolDef
from recruiter.llm.anthropic import AnthropicLLMClient


def _block(type_: str, **kwargs):
    block = MagicMock()
    block.type = type_
    for k, v in kwargs.items():
        setattr(block, k, v)
    return block


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_text_only(monkeypatch) -> None:
    response = MagicMock()
    response.content = [_block("text", text="Marie has 8 years.")]
    response.stop_reason = "end_turn"

    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    turn = await client.chat_with_tools(
        [ChatTurn(role="user", content="hi")],
        [ToolDef(name="get_candidate", description="d", input_schema={"type": "object"})],
        system="be brief",
    )
    assert turn.text == "Marie has 8 years."
    assert turn.tool_calls == []

    kwargs = client._client.messages.create.call_args.kwargs
    assert kwargs["system"] == "be brief"
    assert kwargs["tools"] == [{
        "name": "get_candidate", "description": "d", "input_schema": {"type": "object"},
    }]


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_returns_tool_use() -> None:
    response = MagicMock()
    response.content = [
        _block("text", text="Let me check."),
        _block("tool_use", id="toolu_1", name="get_candidate", input={"q": "x"}),
    ]
    response.stop_reason = "tool_use"

    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    turn = await client.chat_with_tools([ChatTurn(role="user", content="?")], [])
    assert turn.text == "Let me check."
    assert turn.tool_calls == [ToolCall(id="toolu_1", name="get_candidate", arguments={"q": "x"})]


@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_serializes_history() -> None:
    response = MagicMock()
    response.content = [_block("text", text="ok")]
    response.stop_reason = "end_turn"
    client = AnthropicLLMClient(api_key="x", model="claude-x")
    client._client.messages.create = AsyncMock(return_value=response)

    history = [
        ChatTurn(role="user", content="hi"),
        ChatTurn(role="assistant", content="thinking",
                 tool_calls=[ToolCall(id="t1", name="get_candidate", arguments={})]),
        ChatTurn(role="tool", tool_call_id="t1", tool_name="get_candidate",
                 tool_result={"full_name": "Marie"}),
    ]
    await client.chat_with_tools(history, [])
    msgs = client._client.messages.create.call_args.kwargs["messages"]
    assert msgs[0] == {"role": "user", "content": "hi"}
    assert msgs[1]["role"] == "assistant"
    assert any(b["type"] == "tool_use" and b["id"] == "t1" for b in msgs[1]["content"])
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "t1",
        "content": '{"full_name": "Marie"}',
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_anthropic_chat_with_tools.py -v`
Expected: FAIL — missing `chat_with_tools`.

- [ ] **Step 3: Implement `chat_with_tools` on `AnthropicLLMClient`**

Add to `src/recruiter/llm/anthropic.py` (inside the class):

```python
async def chat_with_tools(
    self,
    messages: "list[ChatTurn]",
    tools: "list[ToolDef]",
    *,
    system: str | None = None,
    max_tokens: int = 2048,
) -> "AssistantTurn":
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
```

Add at module level:

```python
def _chat_turn_to_anthropic(turn: "ChatTurn") -> dict:
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
```

Add imports at top:

```python
from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall, ToolDef
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_anthropic_chat_with_tools.py tests/unit/test_anthropic_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/llm/anthropic.py tests/unit/test_anthropic_chat_with_tools.py
git commit -m "feat(llm): implement chat_with_tools for Anthropic client"
```

---

## Task 5: Read tools (5)

**Files:**
- Create: `src/recruiter/agent/tools.py`
- Create: `tests/unit/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests for read tools**

`tests/unit/test_agent_tools.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.tools import TOOLS, get_tool_handler
from recruiter.models import Application, Candidate, Job, Stage


async def _seed(session: AsyncSession) -> int:
    job = Job(title="Backend", description="Build APIs", criteria=[
        {"name": "rust", "weight": 0.5, "description": "rust experience"},
    ])
    session.add(job); await session.flush()
    candidate = Candidate(
        source_type="paste", full_name="Marie Lefèvre", email="m@example.com",
        skills=["Rust", "tokio"],
        experience=[{"title": "Staff", "company": "Datadome", "start": "2022", "end": "present"}],
    )
    session.add(candidate); await session.flush()
    app = Application(
        job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED,
        score=92,
        score_breakdown=[{"criterion": "rust", "weight": 0.5, "score": 92, "rationale": "8y"}],
        score_rationale="strong",
        notes=None,
    )
    session.add(app); await session.commit()
    return app.id


@pytest.mark.asyncio
async def test_get_candidate(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    handler = get_tool_handler("get_candidate")
    result = await handler(db_session_with_schema, app_id, {})
    assert result["full_name"] == "Marie Lefèvre"
    assert result["email"] == "m@example.com"
    assert "Rust" in result["skills"]
    assert result["experience"][0]["company"] == "Datadome"


@pytest.mark.asyncio
async def test_get_application(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_application")(db_session_with_schema, app_id, {})
    assert result["stage"] == "scored"
    assert result["score"] == 92
    assert result["validated_at"] is None


@pytest.mark.asyncio
async def test_get_score_breakdown(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_score_breakdown")(db_session_with_schema, app_id, {})
    assert result["score"] == 92
    assert result["rationale"] == "strong"
    assert result["breakdown"][0]["criterion"] == "rust"


@pytest.mark.asyncio
async def test_get_job(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_job")(db_session_with_schema, app_id, {})
    assert result["title"] == "Backend"
    assert result["criteria"][0]["name"] == "rust"
    assert result["status"] == "open"


@pytest.mark.asyncio
async def test_list_other_applications_excludes_self(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    # Add a second job + second application for the same candidate
    candidate_id = (await db_session_with_schema.get(Application, app_id)).candidate_id
    job2 = Job(title="DevOps", description="ops", criteria=[])
    db_session_with_schema.add(job2); await db_session_with_schema.flush()
    app2 = Application(job_id=job2.id, candidate_id=candidate_id, stage=Stage.EXTRACTING)
    db_session_with_schema.add(app2); await db_session_with_schema.commit()

    result = await get_tool_handler("list_other_applications_for_candidate")(
        db_session_with_schema, app_id, {}
    )
    assert len(result) == 1
    assert result[0]["application_id"] == app2.id
    assert result[0]["job_title"] == "DevOps"
    assert result[0]["stage"] == "extracting"


def test_tools_registry_lists_eight_tools() -> None:
    names = [t.name for t in TOOLS]
    expected = {"get_candidate", "get_application", "get_score_breakdown", "get_job",
                "list_other_applications_for_candidate", "save_note",
                "validate_application", "reject_application"}
    assert set(names) == expected
    assert len(names) == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_agent_tools.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement read tools**

`src/recruiter/agent/tools.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.types import ToolDef
from recruiter.models import Application, Candidate, Job

ToolHandler = Callable[[AsyncSession, int, dict], Awaitable[dict | list]]

_HANDLERS: dict[str, ToolHandler] = {}


def _register(name: str):
    def deco(fn: ToolHandler) -> ToolHandler:
        _HANDLERS[name] = fn
        return fn
    return deco


def get_tool_handler(name: str) -> ToolHandler:
    if name not in _HANDLERS:
        raise KeyError(f"unknown tool: {name}")
    return _HANDLERS[name]


@_register("get_candidate")
async def _get_candidate(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    candidate = await session.get(Candidate, app.candidate_id)
    if candidate is None:
        return {"error": "candidate not found"}
    return {
        "full_name": candidate.full_name,
        "email": candidate.email,
        "phone": candidate.phone,
        "location": candidate.location,
        "headline": candidate.headline,
        "summary": candidate.summary,
        "skills": candidate.skills or [],
        "experience": candidate.experience or [],
        "education": candidate.education or [],
        "links": candidate.links or [],
    }


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


@_register("get_application")
async def _get_application(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    return {
        "stage": app.stage.value if app.stage else None,
        "score": app.score,
        "validated_at": _iso(app.validated_at),
        "invited_at": _iso(app.invited_at),
        "rejected_at": _iso(app.rejected_at),
        "notes": app.notes,
    }


@_register("get_score_breakdown")
async def _get_score_breakdown(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    return {
        "score": app.score,
        "rationale": app.score_rationale,
        "breakdown": app.score_breakdown or [],
    }


@_register("get_job")
async def _get_job(session: AsyncSession, application_id: int, args: dict) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    job = await session.get(Job, app.job_id)
    if job is None:
        return {"error": "job not found"}
    return {
        "title": job.title,
        "description": job.description,
        "criteria": job.criteria or [],
        "status": job.status.value if job.status else None,
    }


@_register("list_other_applications_for_candidate")
async def _list_other(session: AsyncSession, application_id: int, args: dict) -> list[dict]:
    app = await session.get(Application, application_id)
    if app is None:
        return []
    rows = (await session.execute(
        select(Application, Job.title)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == app.candidate_id)
        .where(Application.id != application_id)
        .order_by(Application.created_at.desc())
    )).all()
    return [
        {
            "application_id": other.id,
            "job_title": job_title,
            "stage": other.stage.value if other.stage else None,
            "score": other.score,
            "created_at": _iso(other.created_at),
        }
        for other, job_title in rows
    ]


# JSON Schema definitions — input_schema=={"type":"object","properties":{}} for no-arg tools.
_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS: list[ToolDef] = [
    ToolDef(name="get_candidate",
            description="Read the candidate profile (name, email, skills, experience, education, links).",
            input_schema=_NO_ARGS),
    ToolDef(name="get_application",
            description="Read this application's stage, score, timestamps, and notes.",
            input_schema=_NO_ARGS),
    ToolDef(name="get_score_breakdown",
            description="Read the LLM-generated score and per-criterion rationale.",
            input_schema=_NO_ARGS),
    ToolDef(name="get_job",
            description="Read the job's title, description, and scoring criteria.",
            input_schema=_NO_ARGS),
    ToolDef(name="list_other_applications_for_candidate",
            description="List the same candidate's applications to other jobs (excludes this one).",
            input_schema=_NO_ARGS),
    # write tools added in next task
]
```

- [ ] **Step 4: Run read-tool tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_agent_tools.py -v -k "not save_note and not validate and not reject and not eight_tools"`
Expected: 5 passes (the read tool tests).

The `test_tools_registry_lists_eight_tools` will fail until Task 6 — that's expected.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/agent/tools.py tests/unit/test_agent_tools.py
git commit -m "feat(agent): add 5 read tools (candidate/application/score/job/siblings)"
```

---

## Task 6: Undo store + write tools (3) with guardrails

**Files:**
- Create: `src/recruiter/agent/undo.py`
- Create: `tests/unit/test_agent_undo.py`
- Modify: `src/recruiter/agent/tools.py`
- Modify: `tests/unit/test_agent_tools.py`

- [ ] **Step 1: Write failing tests for undo store**

`tests/unit/test_agent_undo.py`:

```python
import time

import pytest

from recruiter.agent.undo import UndoStore


def test_issue_and_consume() -> None:
    store = UndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert isinstance(token, str) and len(token) >= 16
    payload = store.consume(token)
    assert payload == {"application_id": 1, "previous_stage": "scored"}


def test_consume_returns_none_for_unknown_token() -> None:
    store = UndoStore(ttl_seconds=60)
    assert store.consume("does-not-exist") is None


def test_consume_is_one_shot() -> None:
    store = UndoStore(ttl_seconds=60)
    token = store.issue(application_id=1, previous_stage="scored")
    assert store.consume(token) is not None
    assert store.consume(token) is None


def test_consume_after_ttl_returns_none() -> None:
    store = UndoStore(ttl_seconds=0.01)
    token = store.issue(application_id=1, previous_stage="scored")
    time.sleep(0.05)
    assert store.consume(token) is None
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_agent_undo.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement undo store**

`src/recruiter/agent/undo.py`:

```python
import secrets
import time
from threading import Lock


class UndoStore:
    """In-memory token store for one-shot stage reversals.

    Process-local: tokens are lost on restart, which is acceptable — the user
    just loses the Undo button for that turn. Audit history persists in
    chat_messages and event_logs.
    """

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    def issue(self, *, application_id: int, previous_stage: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = (time.monotonic(), {
                "application_id": application_id,
                "previous_stage": previous_stage,
            })
        return token

    def consume(self, token: str) -> dict | None:
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry is None:
            return None
        issued_at, payload = entry
        if time.monotonic() - issued_at > self._ttl:
            return None
        return payload


_default = UndoStore(ttl_seconds=900.0)


def get_default_undo_store() -> UndoStore:
    return _default
```

- [ ] **Step 4: Run undo tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_agent_undo.py -v`
Expected: PASS.

- [ ] **Step 5: Add failing tests for the 3 write tools**

Append to `tests/unit/test_agent_tools.py`:

```python
import re
from datetime import datetime, timezone

from recruiter.agent.tools import get_tool_handler
from recruiter.agent.undo import UndoStore


@pytest.mark.asyncio
async def test_save_note_appends_to_application_notes(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("save_note")(
        db_session_with_schema, app_id, {"text": "promising candidate"}
    )
    assert result["ok"] is True
    app = await db_session_with_schema.get(Application, app_id)
    assert app.notes is not None
    assert "promising candidate" in app.notes


@pytest.mark.asyncio
async def test_save_note_appends_with_timestamp(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    await get_tool_handler("save_note")(db_session_with_schema, app_id, {"text": "first"})
    await get_tool_handler("save_note")(db_session_with_schema, app_id, {"text": "second"})
    app = await db_session_with_schema.get(Application, app_id)
    assert "first" in app.notes
    assert "second" in app.notes
    # both notes preserved
    assert app.notes.index("first") < app.notes.index("second")


@pytest.mark.asyncio
async def test_validate_from_scored_succeeds(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    store = UndoStore(ttl_seconds=60)
    result = await get_tool_handler("validate_application")(
        db_session_with_schema, app_id, {"notes": "looks great"}, undo_store=store,
    )
    assert result["ok"] is True
    assert result["previous_stage"] == "scored"
    assert isinstance(result["undo_token"], str)
    app = await db_session_with_schema.get(Application, app_id)
    assert app.stage.value == "validated"
    assert app.validated_at is not None
    assert "looks great" in (app.notes or "")


@pytest.mark.asyncio
async def test_validate_from_extracting_blocked(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    app = await db_session_with_schema.get(Application, app_id)
    app.stage = Stage.EXTRACTING
    await db_session_with_schema.commit()

    result = await get_tool_handler("validate_application")(
        db_session_with_schema, app_id, {}, undo_store=UndoStore(ttl_seconds=60),
    )
    assert "error" in result
    assert "extracting" in result["error"].lower()


@pytest.mark.asyncio
async def test_reject_from_scored_succeeds(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    store = UndoStore(ttl_seconds=60)
    result = await get_tool_handler("reject_application")(
        db_session_with_schema, app_id, {"reason": "no Rust experience"},
        undo_store=store,
    )
    assert result["ok"] is True
    assert result["previous_stage"] == "scored"
    app = await db_session_with_schema.get(Application, app_id)
    assert app.stage.value == "rejected"
    assert app.rejected_at is not None
    assert "no Rust experience" in (app.notes or "")


@pytest.mark.asyncio
async def test_reject_from_invited_blocked(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    app = await db_session_with_schema.get(Application, app_id)
    app.stage = Stage.INVITED
    await db_session_with_schema.commit()

    result = await get_tool_handler("reject_application")(
        db_session_with_schema, app_id, {"reason": "x"},
        undo_store=UndoStore(ttl_seconds=60),
    )
    assert "error" in result
    assert "invited" in result["error"].lower()
```

- [ ] **Step 6: Run write-tool tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_agent_tools.py -v -k "save_note or validate or reject or eight_tools"`
Expected: FAIL — handlers and ToolDef registrations missing.

- [ ] **Step 7: Implement write tools + guardrails**

Append to `src/recruiter/agent/tools.py`:

```python
from datetime import datetime, timezone

from recruiter.agent.undo import UndoStore, get_default_undo_store
from recruiter.models import Stage


def _append_note(app: Application, text: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"[{stamp}] {text}"
    app.notes = (app.notes + "\n\n" + line) if app.notes else line


@_register("save_note")
async def _save_note(session: AsyncSession, application_id: int, args: dict) -> dict:
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    _append_note(app, text)
    await session.commit()
    return {"ok": True, "note_id": application_id}


_VALIDATE_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}
_REJECT_FROM = {Stage.SCORED, Stage.VALIDATED, Stage.REJECTED}


async def _validate_application(
    session: AsyncSession,
    application_id: int,
    args: dict,
    *,
    undo_store: UndoStore | None = None,
) -> dict:
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _VALIDATE_FROM:
        return {"error": f"stage {app.stage.value} cannot move to validated"}
    previous = app.stage.value
    app.stage = Stage.VALIDATED
    app.validated_at = datetime.now(timezone.utc)
    notes_arg = (args.get("notes") or "").strip()
    if notes_arg:
        _append_note(app, notes_arg)
    await session.commit()
    store = undo_store or get_default_undo_store()
    token = store.issue(application_id=application_id, previous_stage=previous)
    return {"ok": True, "previous_stage": previous, "undo_token": token}


async def _reject_application(
    session: AsyncSession,
    application_id: int,
    args: dict,
    *,
    undo_store: UndoStore | None = None,
) -> dict:
    reason = (args.get("reason") or "").strip()
    if not reason:
        return {"error": "reason is required"}
    app = await session.get(Application, application_id)
    if app is None:
        return {"error": "application not found"}
    if app.stage not in _REJECT_FROM:
        return {"error": f"stage {app.stage.value} cannot move to rejected"}
    previous = app.stage.value
    app.stage = Stage.REJECTED
    app.rejected_at = datetime.now(timezone.utc)
    _append_note(app, f"Rejected: {reason}")
    await session.commit()
    store = undo_store or get_default_undo_store()
    token = store.issue(application_id=application_id, previous_stage=previous)
    return {"ok": True, "previous_stage": previous, "undo_token": token}


_HANDLERS["validate_application"] = _validate_application
_HANDLERS["reject_application"] = _reject_application


# Append the write tools to the registry
TOOLS.extend([
    ToolDef(
        name="save_note",
        description="Append a free-form note (timestamped) to this application's notes field.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 1}},
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="validate_application",
        description="Mark this candidate as validated (i.e., approved for the next interview step). Reversible until the recruiter sends an interview invitation.",
        input_schema={
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "additionalProperties": False,
        },
    ),
    ToolDef(
        name="reject_application",
        description="Mark this candidate as rejected. Reversible until the recruiter sends an interview invitation. The reason will be appended to the notes.",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 1}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    ),
])
```

- [ ] **Step 8: Run all tool tests, verify pass**

Run: `.venv/bin/pytest tests/unit/test_agent_tools.py tests/unit/test_agent_undo.py -v`
Expected: PASS for all (8 tools test passes too).

- [ ] **Step 9: Commit**

```bash
git add src/recruiter/agent/undo.py src/recruiter/agent/tools.py \
  tests/unit/test_agent_undo.py tests/unit/test_agent_tools.py
git commit -m "feat(agent): add write tools (save_note, validate, reject) + undo store"
```

---

## Task 7: NDJSON event taxonomy

**Files:**
- Create: `src/recruiter/agent/events.py`
- Create: `tests/unit/test_agent_events.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_agent_events.py`:

```python
import json

from recruiter.agent.events import (
    error_event,
    message_done_event,
    message_event,
    message_delta_event,
    serialize_event,
    tool_call_result_event,
    tool_call_start_event,
)


def _parse(line: str) -> dict:
    assert line.endswith("\n")
    return json.loads(line)


def test_message_event_serializes_with_newline() -> None:
    line = serialize_event(message_event(role="user", id=42, content="hi"))
    parsed = _parse(line)
    assert parsed == {"type": "message", "role": "user", "id": 42, "content": "hi"}


def test_tool_call_start_event() -> None:
    parsed = _parse(serialize_event(
        tool_call_start_event(id="tc_1", name="get_candidate", arguments={"x": 1})
    ))
    assert parsed == {"type": "tool_call_start", "id": "tc_1", "name": "get_candidate",
                      "arguments": {"x": 1}}


def test_tool_call_result_event() -> None:
    parsed = _parse(serialize_event(
        tool_call_result_event(id="tc_1", name="get_candidate", result={"full_name": "Marie"})
    ))
    assert parsed == {"type": "tool_call_result", "id": "tc_1", "name": "get_candidate",
                      "result": {"full_name": "Marie"}}


def test_message_delta_event() -> None:
    parsed = _parse(serialize_event(message_delta_event(text="hi there")))
    assert parsed == {"type": "message_delta", "text": "hi there"}


def test_message_done_event() -> None:
    parsed = _parse(serialize_event(message_done_event(id=99)))
    assert parsed == {"type": "message_done", "id": 99}


def test_error_event() -> None:
    parsed = _parse(serialize_event(error_event(detail="boom", phase="llm")))
    assert parsed == {"type": "error", "detail": "boom", "phase": "llm"}


def test_serialize_handles_unicode() -> None:
    line = serialize_event(message_delta_event(text="Marie Lefèvre"))
    assert "Marie Lefèvre" in line
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_agent_events.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement events**

`src/recruiter/agent/events.py`:

```python
import json
from typing import Any, Literal


def message_event(*, role: str, id: int, content: str | None) -> dict:
    return {"type": "message", "role": role, "id": id, "content": content}


def tool_call_start_event(*, id: str, name: str, arguments: dict) -> dict:
    return {"type": "tool_call_start", "id": id, "name": name, "arguments": arguments}


def tool_call_result_event(*, id: str, name: str, result: Any) -> dict:
    return {"type": "tool_call_result", "id": id, "name": name, "result": result}


def message_delta_event(*, text: str) -> dict:
    return {"type": "message_delta", "text": text}


def message_done_event(*, id: int) -> dict:
    return {"type": "message_done", "id": id}


def error_event(*, detail: str, phase: Literal["llm", "tool", "persist", "agent"]) -> dict:
    return {"type": "error", "detail": detail, "phase": phase}


def serialize_event(event: dict) -> str:
    """One JSON object per line, trailing newline; non-ASCII passes through."""
    return json.dumps(event, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_agent_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/agent/events.py tests/unit/test_agent_events.py
git commit -m "feat(agent): add NDJSON event taxonomy + serializer"
```

---

## Task 8: Agent loop (`run_turn`)

**Files:**
- Create: `src/recruiter/agent/chat.py`
- Create: `tests/unit/test_agent_chat_loop.py`

- [ ] **Step 1: Write failing tests for the loop**

`tests/unit/test_agent_chat_loop.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.chat import run_turn
from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.agent.undo import UndoStore
from recruiter.llm.client import FakeLLMClient
from recruiter.models import Application, Candidate, ChatMessage, Job, Stage


async def _seed_app(session: AsyncSession) -> int:
    job = Job(title="Backend", description="x", criteria=[])
    session.add(job); await session.flush()
    candidate = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
    session.add(candidate); await session.flush()
    app = Application(job_id=job.id, candidate_id=candidate.id, stage=Stage.SCORED, score=80)
    session.add(app); await session.commit()
    return app.id


async def _collect(generator):
    return [event async for event in generator]


@pytest.mark.asyncio
async def test_zero_tool_turn(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text="Marie has strong async Rust experience.", tool_calls=[]),
    ])

    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="tell me about her", llm=fake, undo_store=UndoStore(),
    ))

    types = [e["type"] for e in events]
    assert types == ["message", "message_delta", "message_done"]
    assert events[0]["role"] == "user"
    assert events[1]["text"] == "Marie has strong async Rust experience."

    rows = (await db_session_with_schema.execute(
        ChatMessage.__table__.select().order_by(ChatMessage.id)
    )).all()
    assert len(rows) == 2  # user + assistant
    assert rows[0].role == "user" and rows[0].content == "tell me about her"
    assert rows[1].role == "assistant" and rows[1].content.startswith("Marie")


@pytest.mark.asyncio
async def test_one_tool_then_text(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="get_candidate", arguments={}),
        ]),
        AssistantTurn(text="Her email is m@example.com.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="email?", llm=fake, undo_store=UndoStore(),
    ))
    types = [e["type"] for e in events]
    assert types == [
        "message", "tool_call_start", "tool_call_result",
        "message_delta", "message_done",
    ]
    assert events[2]["result"]["email"] == "m@example.com"


@pytest.mark.asyncio
async def test_tool_failure_is_non_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="not_a_real_tool", arguments={}),
        ]),
        AssistantTurn(text="Sorry, that didn't work.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="?", llm=fake, undo_store=UndoStore(),
    ))
    # tool_call_result carries an error payload, but the turn still completes
    result_event = next(e for e in events if e["type"] == "tool_call_result")
    assert "error" in result_event["result"]
    assert events[-1]["type"] == "message_done"


@pytest.mark.asyncio
async def test_llm_exception_is_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)

    class Boom:
        async def chat_with_tools(self, *a, **kw):
            raise RuntimeError("api down")

    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="?", llm=Boom(), undo_store=UndoStore(),
    ))
    types = [e["type"] for e in events]
    assert types[-1] == "error"
    assert "message_done" not in types
    assert events[-1]["phase"] == "llm"
    assert "api down" in events[-1]["detail"]


@pytest.mark.asyncio
async def test_max_iterations_terminal(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    # Always emit a tool call, never a final answer
    looping = [
        AssistantTurn(text=None, tool_calls=[ToolCall(id=f"t{i}", name="get_candidate", arguments={})])
        for i in range(20)
    ]
    fake = FakeLLMClient(tool_turn_responses=looping)
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="loop", llm=fake, undo_store=UndoStore(),
        max_steps=3,
    ))
    err = events[-1]
    assert err["type"] == "error" and err["phase"] == "agent"
    assert "max iterations" in err["detail"].lower()


@pytest.mark.asyncio
async def test_validate_tool_through_loop(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed_app(db_session_with_schema)
    fake = FakeLLMClient(tool_turn_responses=[
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={"notes": "looks great"}),
        ]),
        AssistantTurn(text="Validated.", tool_calls=[]),
    ])
    events = await _collect(run_turn(
        session=db_session_with_schema, application_id=app_id,
        user_message="validate her", llm=fake, undo_store=UndoStore(),
    ))
    result_event = next(e for e in events if e["type"] == "tool_call_result")
    assert result_event["result"]["ok"] is True
    assert "undo_token" in result_event["result"]
    app = await db_session_with_schema.get(Application, app_id)
    assert app.stage.value == "validated"
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/pytest tests/unit/test_agent_chat_loop.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the loop**

`src/recruiter/agent/chat.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.events import (
    error_event,
    message_delta_event,
    message_done_event,
    message_event,
    tool_call_result_event,
    tool_call_start_event,
)
from recruiter.agent.tools import TOOLS, get_tool_handler
from recruiter.agent.types import AssistantTurn, ChatTurn, ToolCall
from recruiter.agent.undo import UndoStore
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, ChatMessage, Job, MessageRole

MAX_STEPS_DEFAULT = 8


async def _load_history(session: AsyncSession, application_id: int) -> list[ChatTurn]:
    rows = (await session.execute(
        select(ChatMessage)
        .where(ChatMessage.application_id == application_id)
        .order_by(ChatMessage.id.asc())
    )).scalars().all()
    return [
        ChatTurn(
            role=row.role.value if hasattr(row.role, "value") else row.role,
            content=row.content,
            tool_calls=[ToolCall(**tc) for tc in (row.tool_calls or [])],
            tool_call_id=row.tool_call_id,
            tool_name=row.tool_name,
            tool_result=row.tool_result,
        )
        for row in rows
    ]


def _system_prompt(*, recruiter_name: str | None, candidate_full_name: str | None, job_title: str | None) -> str:
    rn = recruiter_name or "the recruiter"
    cn = candidate_full_name or "this candidate"
    jt = job_title or "this role"
    return (
        f"You are a recruiting assistant helping {rn} evaluate {cn} for {jt}. "
        "You can read this candidate's data and the job's data, save notes, and validate or reject "
        "the candidate (both reversible until the recruiter sends an interview invitation). "
        "Do not make up facts — call tools when uncertain. Keep responses concise."
    )


async def _build_system_prompt(session: AsyncSession, application_id: int) -> str:
    app = await session.get(Application, application_id)
    if app is None:
        return _system_prompt(recruiter_name=None, candidate_full_name=None, job_title=None)
    candidate = await session.get(Candidate, app.candidate_id)
    job = await session.get(Job, app.job_id)
    from recruiter.models import SettingsRow
    settings = await session.get(SettingsRow, 1)
    return _system_prompt(
        recruiter_name=(settings.recruiter_name if settings else None),
        candidate_full_name=(candidate.full_name if candidate else None),
        job_title=(job.title if job else None),
    )


async def run_turn(
    *,
    session: AsyncSession,
    application_id: int,
    user_message: str,
    llm: LLMClient,
    undo_store: UndoStore,
    max_steps: int = MAX_STEPS_DEFAULT,
) -> AsyncIterator[dict]:
    """Yield NDJSON event dicts for one user turn.

    The session passed in is used for all reads + writes — the caller commits
    via the request lifecycle. Tool handlers commit on their own (they need to
    persist state before the LLM sees the result).
    """
    # 1. Persist + emit user message
    user_row = ChatMessage(
        application_id=application_id,
        role=MessageRole.USER,
        content=user_message,
    )
    session.add(user_row)
    await session.commit()
    await session.refresh(user_row)
    yield message_event(role="user", id=user_row.id, content=user_message)

    # 2. Build system prompt + history
    try:
        system = await _build_system_prompt(session, application_id)
    except Exception as exc:
        yield error_event(detail=f"failed to load context: {exc}", phase="persist")
        return

    # 3. Loop
    last_assistant_id: int | None = None
    for step in range(max_steps):
        history = await _load_history(session, application_id)

        try:
            turn: AssistantTurn = await llm.chat_with_tools(
                history, TOOLS, system=system,
            )
        except Exception as exc:
            err_row = ChatMessage(
                application_id=application_id,
                role=MessageRole.ASSISTANT,
                content=f"(LLM error: {exc})",
            )
            session.add(err_row)
            await session.commit()
            yield error_event(detail=str(exc), phase="llm")
            return

        if not turn.tool_calls:
            text = turn.text or ""
            assistant_row = ChatMessage(
                application_id=application_id,
                role=MessageRole.ASSISTANT,
                content=text,
            )
            session.add(assistant_row)
            await session.commit()
            await session.refresh(assistant_row)
            yield message_delta_event(text=text)
            yield message_done_event(id=assistant_row.id)
            return

        # Persist assistant tool_calls turn
        assistant_row = ChatMessage(
            application_id=application_id,
            role=MessageRole.ASSISTANT,
            content=turn.text,
            tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in turn.tool_calls],
        )
        session.add(assistant_row)
        await session.commit()
        await session.refresh(assistant_row)
        last_assistant_id = assistant_row.id

        # Execute each tool call sequentially
        for tc in turn.tool_calls:
            yield tool_call_start_event(id=tc.id, name=tc.name, arguments=tc.arguments)
            try:
                handler = get_tool_handler(tc.name)
                if tc.name in ("validate_application", "reject_application"):
                    result = await handler(
                        session, application_id, tc.arguments, undo_store=undo_store,
                    )
                else:
                    result = await handler(session, application_id, tc.arguments)
            except Exception as exc:
                result = {"error": str(exc)}

            tool_row = ChatMessage(
                application_id=application_id,
                role=MessageRole.TOOL,
                tool_call_id=tc.id,
                tool_name=tc.name,
                tool_result=result,
            )
            session.add(tool_row)
            await session.commit()
            yield tool_call_result_event(id=tc.id, name=tc.name, result=result)

    # Loop exhausted without a final answer
    err_row = ChatMessage(
        application_id=application_id,
        role=MessageRole.ASSISTANT,
        content="(agent stopped: max iterations reached)",
    )
    session.add(err_row)
    await session.commit()
    yield error_event(detail="max iterations reached", phase="agent")
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/pytest tests/unit/test_agent_chat_loop.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/agent/chat.py tests/unit/test_agent_chat_loop.py
git commit -m "feat(agent): implement run_turn agent loop with tool execution"
```

---

## Task 9: API endpoint — POST/GET chat + POST undo

**Files:**
- Create: `src/recruiter/api/chat.py`
- Create: `src/recruiter/schemas/chat.py`
- Create: `tests/api/test_chat_api.py`
- Modify: `src/recruiter/main.py`
- Modify: `recruiter-frontend/src/lib/query-keys.ts`

- [ ] **Step 1: Write failing API tests**

`tests/api/test_chat_api.py`:

```python
import json

import pytest
from httpx import AsyncClient

from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app


@pytest.fixture
def fake_llm():
    return FakeLLMClient(tool_turn_responses=[])


@pytest.fixture
def with_fake_llm(fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    try:
        yield fake_llm
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _create_scored_app(api_client: AsyncClient) -> int:
    job = await api_client.post("/api/jobs", json={
        "title": "Backend", "description": "x", "criteria": []
    })
    job_id = job.json()["id"]
    # Use the paste path with a FakeLLM-friendly seeded application — but the
    # candidates endpoint needs a real LLM. For test simplicity we insert via
    # a helper API that already exists (the test conftest seeds applications
    # in the same way other tests do).
    # The simplest approach: use the model directly via the engine override.
    from recruiter.api.candidates import get_engine_dep
    engine = app.dependency_overrides[get_engine_dep]()
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from recruiter.models import Application, Candidate, Stage
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        c = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
        session.add(c); await session.flush()
        a = Application(job_id=job_id, candidate_id=c.id, stage=Stage.SCORED, score=80)
        session.add(a); await session.commit()
        return a.id


@pytest.mark.asyncio
async def test_chat_post_streams_ndjson(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text="Hello.", tool_calls=[]),
    ])

    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "hi"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = []
        async for line in r.aiter_lines():
            if line:
                events.append(json.loads(line))

    assert [e["type"] for e in events] == ["message", "message_delta", "message_done"]


@pytest.mark.asyncio
async def test_chat_get_history_returns_persisted_messages(api_client, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([AssistantTurn(text="ok", tool_calls=[])])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "hi"},
    ) as r:
        async for _ in r.aiter_lines():
            pass

    history = await api_client.get(f"/api/applications/{app_id}/chat")
    assert history.status_code == 200
    payload = history.json()
    assert len(payload) == 2
    assert payload[0]["role"] == "user" and payload[0]["content"] == "hi"
    assert payload[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_chat_post_409_when_extracting(api_client: AsyncClient, with_fake_llm) -> None:
    # Seed an application in EXTRACTING stage
    job = await api_client.post("/api/jobs", json={
        "title": "x", "description": "x", "criteria": []
    })
    job_id = job.json()["id"]
    from recruiter.api.candidates import get_engine_dep
    engine = app.dependency_overrides[get_engine_dep]()
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from recruiter.models import Application, Candidate, Stage
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        c = Candidate(source_type="paste"); session.add(c); await session.flush()
        a = Application(job_id=job_id, candidate_id=c.id, stage=Stage.EXTRACTING)
        session.add(a); await session.commit()
        app_id = a.id

    r = await api_client.post(f"/api/applications/{app_id}/chat", json={"message": "hi"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_chat_post_404_when_app_missing(api_client, with_fake_llm) -> None:
    r = await api_client.post("/api/applications/99999/chat", json={"message": "hi"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_undo_reverses_stage_within_ttl(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={}),
        ]),
        AssistantTurn(text="Done.", tool_calls=[]),
    ])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "validate her"},
    ) as r:
        token = None
        async for line in r.aiter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["type"] == "tool_call_result" and ev["name"] == "validate_application":
                token = ev["result"]["undo_token"]

    assert token is not None
    undo = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": token},
    )
    assert undo.status_code == 200
    assert undo.json()["stage"] == "scored"


@pytest.mark.asyncio
async def test_undo_410_for_unknown_token(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    r = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": "not-a-real-token"},
    )
    assert r.status_code == 410
```

- [ ] **Step 2: Define schemas**

`src/recruiter/schemas/chat.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class UndoRequest(BaseModel):
    undo_token: str = Field(min_length=1)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    role: str
    content: str | None
    tool_calls: list | None
    tool_call_id: str | None
    tool_name: str | None
    tool_result: dict | None
    created_at: datetime
```

- [ ] **Step 3: Implement the API**

`src/recruiter/api/chat.py`:

```python
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.agent.chat import run_turn
from recruiter.agent.events import error_event, serialize_event
from recruiter.agent.undo import UndoStore, get_default_undo_store
from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.deps import get_session
from recruiter.llm.client import LLMClient
from recruiter.models import Application, ChatMessage, Stage
from recruiter.schemas.chat import ChatMessageRead, ChatRequest, UndoRequest
from recruiter.schemas.application import ApplicationRead

router = APIRouter(prefix="/api/applications", tags=["chat"])


def get_undo_store() -> UndoStore:
    return get_default_undo_store()


@router.get("/{application_id}/chat", response_model=list[ChatMessageRead])
async def get_chat_history(
    application_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageRead]:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    rows = (await session.execute(
        select(ChatMessage)
        .where(ChatMessage.application_id == application_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )).scalars().all()
    return [ChatMessageRead.model_validate(r) for r in rows]


@router.post("/{application_id}/chat")
async def post_chat(
    application_id: int,
    payload: ChatRequest,
    engine: AsyncEngine = Depends(get_engine_dep),
    llm: LLMClient = Depends(get_llm),
    undo_store: UndoStore = Depends(get_undo_store),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage == Stage.EXTRACTING:
        raise HTTPException(
            status_code=409,
            detail="cannot chat about an application that hasn't been extracted yet",
        )

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def streamer() -> AsyncIterator[bytes]:
        async with SessionLocal() as own_session:
            try:
                async for event in run_turn(
                    session=own_session,
                    application_id=application_id,
                    user_message=payload.message,
                    llm=llm,
                    undo_store=undo_store,
                ):
                    yield serialize_event(event).encode("utf-8")
            except Exception as exc:  # last-resort guard
                yield serialize_event(
                    error_event(detail=f"unexpected: {exc}", phase="persist")
                ).encode("utf-8")

    return StreamingResponse(streamer(), media_type="application/x-ndjson")


@router.post("/{application_id}/undo", response_model=ApplicationRead)
async def post_undo(
    application_id: int,
    payload: UndoRequest,
    session: AsyncSession = Depends(get_session),
    undo_store: UndoStore = Depends(get_undo_store),
) -> ApplicationRead:
    consumed = undo_store.consume(payload.undo_token)
    if consumed is None or consumed.get("application_id") != application_id:
        raise HTTPException(status_code=410, detail="undo token expired or unknown")

    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    previous_stage = consumed["previous_stage"]
    app_row.stage = Stage(previous_stage)
    if previous_stage != "validated":
        app_row.validated_at = None
    if previous_stage != "rejected":
        app_row.rejected_at = None
    app_row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(app_row)
    return ApplicationRead.model_validate(app_row)
```

- [ ] **Step 4: Mount the router**

Edit `src/recruiter/main.py`:

```python
from recruiter.api import applications, candidates, chat, events, jobs, notifications, settings
...
app.include_router(chat.router)
```

- [ ] **Step 5: Add the frontend query key**

Replace the contents of `recruiter-frontend/src/lib/query-keys.ts` with:

```ts
export const queryKeys = {
  jobs: () => ["jobs"] as const,
  job: (id: number) => ["jobs", id] as const,
  jobApplications: (jobId: number) => ["jobs", jobId, "applications"] as const,
  application: (id: number) => ["applications", id] as const,
  chat: (applicationId: number) => ["applications", applicationId, "chat"] as const,
  settings: () => ["settings"] as const,
};
```

- [ ] **Step 6: Run, verify pass**

Run: `.venv/bin/pytest tests/api/test_chat_api.py -v`
Expected: 6 tests pass.

- [ ] **Step 7: Run the entire backend test suite**

Run: `.venv/bin/pytest -x -q`
Expected: all tests pass (no regressions).

- [ ] **Step 8: Commit**

```bash
git add src/recruiter/api/chat.py src/recruiter/schemas/chat.py src/recruiter/main.py \
  tests/api/test_chat_api.py recruiter-frontend/src/lib/query-keys.ts
git commit -m "feat(api): chat endpoints (POST stream / GET history / POST undo)"
```

---

## Task 10: NDJSON parser (frontend)

**Files:**
- Create: `recruiter-frontend/src/lib/ndjson.ts`
- Create: `recruiter-frontend/src/lib/ndjson.test.ts`

- [ ] **Step 1: Write failing test**

`recruiter-frontend/src/lib/ndjson.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { parseNdjsonStream } from "./ndjson";

function streamFrom(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("parseNdjsonStream", () => {
  it("parses one event per line", async () => {
    const stream = streamFrom('{"a":1}\n{"a":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { a: 2 }]);
  });

  it("handles a JSON object split across two chunks", async () => {
    const stream = streamFrom('{"a":', '1}\n{"b":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("yields trailing line without final newline", async () => {
    const stream = streamFrom('{"a":1}\n{"b":2}');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("drops malformed lines with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const stream = streamFrom('{"ok":1}\nnot-json\n{"ok":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ ok: 1 }, { ok: 2 }]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("ignores empty lines", async () => {
    const stream = streamFrom('{"a":1}\n\n{"a":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { a: 2 }]);
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/lib/ndjson.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement parser**

`recruiter-frontend/src/lib/ndjson.ts`:

```ts
export async function* parseNdjsonStream<T = unknown>(
  stream: ReadableStream<Uint8Array>,
): AsyncIterable<T> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try {
        yield JSON.parse(line) as T;
      } catch (err) {
        console.warn("ndjson: dropping malformed line", { line, err });
      }
    }
    if (done) {
      const tail = buf.trim();
      if (tail) {
        try {
          yield JSON.parse(tail) as T;
        } catch (err) {
          console.warn("ndjson: dropping malformed trailing line", { tail, err });
        }
      }
      return;
    }
  }
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/lib/ndjson.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/lib/ndjson.ts recruiter-frontend/src/lib/ndjson.test.ts
git commit -m "feat(frontend): add NDJSON ReadableStream parser"
```

---

## Task 11: `useChat` hook

**Files:**
- Create: `recruiter-frontend/src/hooks/use-chat.ts`
- Create: `recruiter-frontend/src/hooks/use-chat.test.tsx`

- [ ] **Step 1: Write failing test**

`recruiter-frontend/src/hooks/use-chat.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { useChat } from "./use-chat";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const APP_ID = 1;

describe("useChat", () => {
  it("loads history on mount", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([
          { id: 1, application_id: APP_ID, role: "user", content: "hi",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0].content).toBe("hi");
  });

  it("streams a turn and appends events to messages", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([]),
      ),
      http.post(`http://localhost:8000/api/applications/${APP_ID}/chat`, () => {
        const body = [
          { type: "message", role: "user", id: 10, content: "hi" },
          { type: "message_delta", text: "hello back" },
          { type: "message_done", id: 11 },
        ].map((e) => JSON.stringify(e) + "\n").join("");
        return new HttpResponse(body, {
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    expect(result.current.isStreaming).toBe(false);
    const texts = result.current.messages.map((m) => m.content);
    expect(texts).toContain("hi");
    expect(texts).toContain("hello back");
  });

  it("renders an error event into the error state", async () => {
    server.use(
      http.get(`http://localhost:8000/api/applications/${APP_ID}/chat`, () =>
        HttpResponse.json([]),
      ),
      http.post(`http://localhost:8000/api/applications/${APP_ID}/chat`, () => {
        const body = [
          { type: "message", role: "user", id: 1, content: "?" },
          { type: "error", detail: "boom", phase: "llm" },
        ].map((e) => JSON.stringify(e) + "\n").join("");
        return new HttpResponse(body, {
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }),
    );

    const { result } = renderHook(() => useChat(APP_ID), { wrapper: wrap() });
    await waitFor(() => expect(result.current.messages).toEqual([]));
    await act(async () => {
      await result.current.sendMessage("?");
    });
    expect(result.current.error).toBe("boom");
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/hooks/use-chat.test.tsx`
Expected: FAIL — hook missing.

- [ ] **Step 3: Implement hook**

`recruiter-frontend/src/hooks/use-chat.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { parseNdjsonStream } from "@/lib/ndjson";
import { queryKeys } from "@/lib/query-keys";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type ChatRow = {
  id: number;
  application_id: number;
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_calls: { id: string; name: string; arguments: Record<string, unknown> }[] | null;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_result: Record<string, unknown> | null;
  created_at: string;
};

type StreamEvent =
  | { type: "message"; role: string; id: number; content: string }
  | { type: "tool_call_start"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_call_result"; id: string; name: string; result: Record<string, unknown> }
  | { type: "message_delta"; text: string }
  | { type: "message_done"; id: number }
  | { type: "error"; detail: string; phase: string };

export function useChat(applicationId: number) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<ChatRow[]>([]);
  const [isStreaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const history = useQuery({
    queryKey: queryKeys.chat(applicationId),
    queryFn: () => api<ChatRow[]>(`/api/applications/${applicationId}/chat`),
  });

  async function sendMessage(message: string): Promise<void> {
    setError(null);
    setStreaming(true);
    setDraft([]);

    let nextId = -1;
    function pushDraft(row: ChatRow) {
      setDraft((d) => [...d, row]);
    }

    try {
      const response = await fetch(
        `${BASE_URL}/api/applications/${applicationId}/chat`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ message }),
        },
      );
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, await response.text());
      }

      for await (const ev of parseNdjsonStream<StreamEvent>(response.body)) {
        switch (ev.type) {
          case "message":
            pushDraft({
              id: ev.id, application_id: applicationId, role: ev.role as "user",
              content: ev.content, tool_calls: null, tool_call_id: null,
              tool_name: null, tool_result: null,
              created_at: new Date().toISOString(),
            });
            break;
          case "tool_call_start":
            pushDraft({
              id: nextId--, application_id: applicationId, role: "assistant",
              content: null,
              tool_calls: [{ id: ev.id, name: ev.name, arguments: ev.arguments }],
              tool_call_id: null, tool_name: null, tool_result: null,
              created_at: new Date().toISOString(),
            });
            break;
          case "tool_call_result":
            pushDraft({
              id: nextId--, application_id: applicationId, role: "tool",
              content: null, tool_calls: null,
              tool_call_id: ev.id, tool_name: ev.name, tool_result: ev.result,
              created_at: new Date().toISOString(),
            });
            break;
          case "message_delta":
            pushDraft({
              id: nextId--, application_id: applicationId, role: "assistant",
              content: ev.text, tool_calls: null, tool_call_id: null,
              tool_name: null, tool_result: null,
              created_at: new Date().toISOString(),
            });
            break;
          case "message_done":
            // canonical state will reload from server
            break;
          case "error":
            setError(ev.detail);
            break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "stream failed");
    } finally {
      setStreaming(false);
      qc.invalidateQueries({ queryKey: queryKeys.chat(applicationId) });
    }
  }

  const undo = useMutation({
    mutationFn: (token: string) =>
      api(`/api/applications/${applicationId}/undo`, {
        method: "POST",
        json: { undo_token: token },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      qc.invalidateQueries({ queryKey: queryKeys.chat(applicationId) });
    },
  });

  const messages: ChatRow[] = [...(history.data ?? []), ...draft];
  return { messages, sendMessage, isStreaming, error, undo: undo.mutate };
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/hooks/use-chat.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/hooks/use-chat.ts recruiter-frontend/src/hooks/use-chat.test.tsx
git commit -m "feat(frontend): add useChat hook with NDJSON streaming + undo"
```

---

## Task 12: `ChatPanel` component

**Files:**
- Create: `recruiter-frontend/src/components/applications/chat-panel.tsx`
- Create: `recruiter-frontend/src/components/applications/chat-panel.test.tsx`

- [ ] **Step 1: Write failing test**

`recruiter-frontend/src/components/applications/chat-panel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { ChatPanel } from "./chat-panel";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("ChatPanel", () => {
  it("shows empty state with no history", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() =>
      expect(screen.getByText(/ask anything/i)).toBeInTheDocument(),
    );
  });

  it("renders a user message and an assistant message", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "user", content: "hi",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:00Z" },
          { id: 2, application_id: 1, role: "assistant", content: "hello",
            tool_calls: null, tool_call_id: null, tool_name: null, tool_result: null,
            created_at: "2026-05-01T00:00:01Z" },
        ]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("renders a tool-call card collapsed by default and expands on click", async () => {
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "tool", content: null, tool_calls: null,
            tool_call_id: "tc1", tool_name: "get_candidate",
            tool_result: { full_name: "Marie" },
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/get_candidate/)).toBeInTheDocument());
    expect(screen.queryByText(/Marie/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/get_candidate/));
    expect(screen.getByText(/Marie/)).toBeInTheDocument();
  });

  it("renders an Undo button on validate/reject tool results and triggers undo", async () => {
    let undoCalls = 0;
    server.use(
      http.get("http://localhost:8000/api/applications/1/chat", () =>
        HttpResponse.json([
          { id: 1, application_id: 1, role: "tool", content: null, tool_calls: null,
            tool_call_id: "tc1", tool_name: "validate_application",
            tool_result: { ok: true, previous_stage: "scored", undo_token: "tok-123" },
            created_at: "2026-05-01T00:00:00Z" },
        ]),
      ),
      http.post("http://localhost:8000/api/applications/1/undo", () => {
        undoCalls++;
        return HttpResponse.json({
          id: 1, job_id: 1, candidate_id: 1, stage: "scored", score: 80,
          score_breakdown: null, score_rationale: null, notes: null,
          validated_at: null, invited_at: null, scheduled_at: null, rejected_at: null,
          created_at: "2026-05-01T00:00:00Z", updated_at: "2026-05-01T00:00:01Z",
        });
      }),
    );
    render(<ChatPanel applicationId={1} />, { wrapper: wrap() });
    const button = await screen.findByRole("button", { name: /undo/i });
    await userEvent.click(button);
    await waitFor(() => expect(undoCalls).toBe(1));
  });
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/chat-panel.test.tsx`
Expected: FAIL — component missing.

- [ ] **Step 3: Implement `ChatPanel`**

`recruiter-frontend/src/components/applications/chat-panel.tsx`:

```tsx
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ChatRow, useChat } from "@/hooks/use-chat";

interface Props {
  applicationId: number;
}

export function ChatPanel({ applicationId }: Props) {
  const { messages, sendMessage, isStreaming, error, undo } = useChat(applicationId);
  const [input, setInput] = useState("");

  async function onSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(text);
  }

  return (
    <div className="flex flex-col h-full bg-card border-l">
      <div className="px-4 py-2 border-b font-medium">Chat</div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">Ask anything about this candidate.</p>
        )}
        {messages.map((m, i) => (
          <MessageRow key={`${m.id}-${i}`} row={m} onUndo={(t) => undo(t)} />
        ))}
        {isStreaming && (
          <p className="text-xs text-muted-foreground animate-pulse">Thinking…</p>
        )}
        {error && (
          <p className="text-xs text-red-600 border border-red-300 rounded p-2 bg-red-50">
            {error}
          </p>
        )}
      </div>
      <div className="p-3 border-t flex gap-2">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything…"
          disabled={isStreaming}
          rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        <Button onClick={onSend} disabled={isStreaming || !input.trim()}>
          Send
        </Button>
      </div>
    </div>
  );
}

function MessageRow({ row, onUndo }: { row: ChatRow; onUndo: (token: string) => void }) {
  if (row.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-primary text-primary-foreground rounded-lg px-3 py-2 max-w-[85%] whitespace-pre-wrap">
          {row.content}
        </div>
      </div>
    );
  }
  if (row.role === "assistant" && !row.tool_calls) {
    return (
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <ReactMarkdown>{row.content || ""}</ReactMarkdown>
      </div>
    );
  }
  if (row.role === "assistant" && row.tool_calls) {
    return (
      <div className="space-y-1">
        {row.content && (
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown>{row.content}</ReactMarkdown>
          </div>
        )}
        {row.tool_calls.map((tc) => (
          <Card key={tc.id} className="p-2 text-xs text-muted-foreground bg-muted/40">
            <code>{tc.name}({JSON.stringify(tc.arguments)})</code>
          </Card>
        ))}
      </div>
    );
  }
  if (row.role === "tool") {
    return <ToolResultCard row={row} onUndo={onUndo} />;
  }
  return null;
}

function ToolResultCard({ row, onUndo }: { row: ChatRow; onUndo: (token: string) => void }) {
  const [open, setOpen] = useState(false);
  const isAction =
    row.tool_name === "validate_application" || row.tool_name === "reject_application";
  const undoToken =
    isAction && row.tool_result && typeof row.tool_result["undo_token"] === "string"
      ? (row.tool_result["undo_token"] as string)
      : null;

  return (
    <Card className="p-2 text-xs space-y-1 border-l-2 border-l-primary/40">
      <button
        type="button"
        className="text-left w-full font-mono text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((o) => !o)}
      >
        ↳ {row.tool_name} {open ? "▼" : "▶"}
      </button>
      {open && (
        <pre className="overflow-x-auto bg-background rounded p-2">
          {JSON.stringify(row.tool_result, null, 2)}
        </pre>
      )}
      {undoToken && (
        <Button size="sm" variant="outline" onClick={() => onUndo(undoToken)}>
          Undo
        </Button>
      )}
    </Card>
  );
}
```

- [ ] **Step 4: Run, verify pass**

Run: `cd recruiter-frontend && npm run test -- src/components/applications/chat-panel.test.tsx`
Expected: PASS (all 4 cases).

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend/src/components/applications/chat-panel.tsx \
  recruiter-frontend/src/components/applications/chat-panel.test.tsx
git commit -m "feat(frontend): add ChatPanel component (markdown + tool cards + undo)"
```

---

## Task 13: Mount `ChatPanel` on the application detail page

**Files:**
- Modify: `recruiter-frontend/src/routes/application-detail.tsx`

- [ ] **Step 1: Replace the placeholder with the real `ChatPanel`**

The file currently renders an `<aside>` with the text "Chat panel coming in Plan D". Replace that aside with the real component. Edit `recruiter-frontend/src/routes/application-detail.tsx` so the file looks exactly like:

```tsx
import { useParams } from "react-router-dom";
import { ActionBar } from "@/components/candidate/action-bar";
import { ChatPanel } from "@/components/applications/chat-panel";
import { ScoreBreakdown } from "@/components/candidate/score-breakdown";
import { useApplication } from "@/hooks/use-application";
import { useCandidate } from "@/hooks/use-candidate";

export default function ApplicationDetail() {
  const { appId } = useParams<{ appId: string }>();
  const id = Number(appId);
  const application = useApplication(id);
  const candidate = useCandidate(application.data?.candidate_id);

  if (application.isLoading) return <p>Loading…</p>;
  if (application.isError)
    return <p className="text-destructive">Failed to load.</p>;
  if (!application.data) return <p>Not found.</p>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6 h-[calc(100vh-8rem)]">
      <div className="space-y-6 overflow-y-auto">
        <header className="space-y-2">
          <h2 className="text-xl font-semibold">
            {candidate.data?.full_name ??
              `Candidate #${application.data.candidate_id}`}
          </h2>
          <p className="text-sm text-muted-foreground capitalize">
            {application.data.stage}
          </p>
          {candidate.data?.email && (
            <p className="text-sm text-muted-foreground">{candidate.data.email}</p>
          )}
          <ActionBar
            application={application.data}
            candidateEmail={candidate.data?.email}
          />
        </header>
        <ScoreBreakdown application={application.data} />
      </div>
      <aside className="rounded border overflow-hidden">
        {application.data.stage === "extracting" ? (
          <div className="p-4 text-sm text-muted-foreground">
            Chat is available once extraction finishes.
          </div>
        ) : (
          <ChatPanel applicationId={id} />
        )}
      </aside>
    </div>
  );
}
```

Notes:
- Mobile (< `lg`) collapses the `aside` below the main column due to `grid-cols-1` on small screens — that's the existing pattern. A full-screen modal trigger is a follow-up; not blocking.
- The `extracting` stage check matches the API guardrail (POST /chat returns 409 in that stage), so we hide the panel UI rather than show an inevitable error.

- [ ] **Step 2: Manually verify in the browser**

Start backend (`RECRUITER_LOCAL_LLM_API_KEY=<key> .venv/bin/uvicorn recruiter.main:app --port 8765`) and frontend (`cd recruiter-frontend && npm run dev`). Open `http://localhost:5173/applications/<id>` for an application that's already `scored`. Verify the chat panel renders, history loads, and you can submit a message.

- [ ] **Step 3: Run frontend tests, verify no regressions**

Run: `cd recruiter-frontend && npm test`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend/src/routes/application-detail.tsx
git commit -m "feat(frontend): mount ChatPanel on application detail page"
```

---

## Task 14: SMOKE.md update

**Files:**
- Modify: `recruiter-frontend/SMOKE.md`

- [ ] **Step 1: Append Plan D smoke checklist**

Add this section to the bottom of `recruiter-frontend/SMOKE.md`:

```markdown
## Plan D — Chat panel

Prereqs: backend + frontend running, an application in stage `scored`, an LLM
provider configured (`/api/settings`).

- [ ] Open `/applications/<scored-app-id>` → chat panel mounted on the right, history empty.
- [ ] Type "summarize her async-Rust experience" + press Enter.
  - [ ] Input disables while streaming, "Thinking…" indicator appears.
  - [ ] Assistant text appears (no tool call card for a simple read query).
- [ ] Type "validate her with note 'strong RustConf signal'".
  - [ ] A `validate_application` tool card renders.
  - [ ] Application stage on the left side / kanban moves to Validated.
  - [ ] An "Undo" button is visible on the tool card.
  - [ ] Click Undo → kanban reverts to Scored within ~1s.
- [ ] Refresh the page → entire conversation reloads from the DB in order.
- [ ] Kill the backend mid-turn → red error banner appears in the panel.
- [ ] Restart backend → next user message succeeds.
```

- [ ] **Step 2: Commit**

```bash
git add recruiter-frontend/SMOKE.md
git commit -m "docs(smoke): add Plan D chat panel checklist"
```

---

## Task 15: End-to-end real-LLM smoke

**Files:** none (verification only)

- [ ] **Step 1: Confirm services are running**

```bash
curl -sf http://localhost:8765/health
curl -sf -o /dev/null -w "frontend:%{http_code}\n" http://localhost:5173
```

- [ ] **Step 2: Confirm Linagora env is set**

```bash
ps -ef | grep 'uvicorn recruiter' | grep -v grep
# the line should include RECRUITER_LOCAL_LLM_API_KEY in the env (or restart with it)
curl -s http://localhost:8765/api/settings | python3 -m json.tool
# expect default_llm_provider == "local",
#   local_llm_url == "https://ai.linagora.com/api/v1",
#   model_overrides.local_model == "openai/gpt-oss-120b:free"
```

- [ ] **Step 3: Walk through the SMOKE.md Plan D checklist**

Use the application from the prior real-LLM smoke (Marie Lefèvre, application id 4). Verify each box.

- [ ] **Step 4: Inspect persisted chat_messages directly to confirm shape**

```bash
.venv/bin/python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from recruiter.config import get_config

async def main():
    eng = create_async_engine(get_config().database_url)
    async with eng.connect() as c:
        rows = (await c.execute(text(
            'SELECT id, role, content, tool_name, tool_result FROM chat_messages '
            'WHERE application_id = 4 ORDER BY id LIMIT 20'
        ))).all()
        for r in rows:
            print(r)
asyncio.run(main())
"
```

Expected: a coherent linear sequence of `user → assistant(tool_calls) → tool(result) → assistant(text)` rows.

- [ ] **Step 5: No commit** — smoke is pass/fail only. If anything failed, file the issue inline and decide whether to fix before proceeding.

---

## Self-review

Quick pass against the spec:

| Spec section | Where it's implemented |
|---|---|
| Architecture (`agent/` package, ChatMessage model) | Tasks 1, 5–9 |
| Data model | Task 1 |
| Backend agent loop (`run_turn` + `chat_with_tools`) | Tasks 2–4, 8 |
| Tool catalog (5 reads + 3 writes) | Tasks 5, 6 |
| Guardrails + undo (15-min TTL) | Task 6 |
| API surface (POST stream / GET / POST undo) | Task 9 |
| NDJSON event taxonomy | Task 7 |
| Frontend (`useChat`, `ChatPanel`, `lib/ndjson`) | Tasks 10–13 |
| Testing strategy | Each task includes tests; Task 15 covers real-LLM smoke |
| SMOKE.md update | Task 14 |
| Open questions (token streaming, summarization, etc.) | Spec only — deferred, no plan tasks |

No placeholders / TODOs / "implement appropriate" lines. All type and method names round-trip across tasks: `chat_with_tools` (Tasks 2–4, 8); `ChatTurn`/`ToolDef`/`ToolCall`/`AssistantTurn` (Task 2 → used in 3, 4, 8); `get_tool_handler` / `TOOLS` (Tasks 5, 6, 8); `UndoStore` / `get_default_undo_store` (Tasks 6, 9); `parseNdjsonStream` (Tasks 10, 11); `useChat` / `ChatRow` (Tasks 11, 12); `ChatPanel` (Tasks 12, 13).
