# Plan D — Per-application chat panel (design)

**Status:** approved 2026-05-01
**Supersedes:** the Plan D section of `docs/superpowers/specs/2026-04-30-plan-b-frontend-design.md`

## Goal

Embed a Claude/GPT-OSS-driven chat assistant into the application detail page so the recruiter can ask grounded questions about a specific candidate ("does her experience match the JD?", "summarize her open-source work") and delegate reversible state transitions ("validate her with note X", "reject the bottom three for no Rust"). The agent reads from the same DB the UI does and writes only through audited tool calls.

## Scope

In:
- One persistent chat thread per `Application`.
- 8 tools: 5 reads (candidate, application, score breakdown, job, sibling applications) + 3 writes (`save_note`, `validate_application`, `reject_application`).
- Auto-execute writes with one-click undo for state changes (notify always stays a manual UI action).
- Provider-agnostic tool-use abstraction `LLMClient.chat_with_tools(...)`, with native adapters for OpenAI-style (`gpt-oss-120b` via Linagora) and Anthropic.
- NDJSON streaming over a single POST.
- Right-side chat panel on `/applications/{id}`; full-screen modal on mobile (per existing responsive rules).

Out:
- Token-level streaming inside an assistant turn (deferred — full-turn events only in v1).
- Multiple threads per application.
- Message editing / regeneration.
- Cross-candidate compare beyond a sibling-applications list.
- Cost accounting beyond what the pipeline already does.
- Notify via the agent — Notify stays a deliberate UI action.

## Architecture

```
recruiter-frontend/src/
├── components/applications/chat-panel.tsx
├── hooks/use-chat.ts
└── lib/ndjson.ts                                  # NDJSON parser

src/recruiter/
├── agent/                                         # NEW package
│   ├── tools.py                                   # JSON Schema + handlers for the 8 tools
│   ├── chat.py                                    # agent loop: chat_with_tools → execute → repeat
│   ├── events.py                                  # NDJSON event taxonomy + serializer
│   └── undo.py                                    # in-memory undo-token store (15-min TTL)
├── llm/client.py                                  # add chat_with_tools(...) to Protocol
├── llm/anthropic.py                               # implement chat_with_tools (Anthropic native)
├── llm/openai_compat.py                           # implement chat_with_tools (OpenAI tools=)
├── api/chat.py                                    # POST /api/applications/{id}/chat (NDJSON)
└── models/chat_message.py                         # ChatMessage table
```

The agent is a stateless loop that lives entirely in `agent/chat.py`. Each request loads message history from `chat_messages`, appends the new user turn, calls `llm.chat_with_tools(...)` in a loop until the model returns a final assistant message with no further tool calls, persisting and streaming each event as it happens. Tools are pure functions in `tools.py` taking `(session, application_id, args)`. They know nothing about LLMs or streaming.

## Data model

One new table, `chat_messages`:

```python
class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id:               Mapped[int]                       # pk
    application_id:   Mapped[int]                       # fk applications.id, indexed
    role:             Mapped[MessageRole]
    content:          Mapped[str | None]                # text for user/assistant; None for pure tool_use
    tool_calls:       Mapped[list[dict] | None]         # [{id, name, arguments}] when role=assistant
    tool_call_id:     Mapped[str | None]                # set when role=tool, links result to call
    tool_name:        Mapped[str | None]                # set when role=tool
    tool_result:      Mapped[dict | None]               # JSON-serializable
    created_at:       Mapped[datetime]
    updated_at:       Mapped[datetime]
```

`role` mirrors the OpenAI/Anthropic conversational shape so we can replay history into either provider without conversion. Tool calls and their results are persisted as separate rows; the conversation reads linearly: user → assistant(with `tool_calls`) → tool(result) → tool(result) → assistant(text) → user…

Alembic migration creates the table plus a `(application_id, created_at)` index.

## Backend agent loop

**`LLMClient.chat_with_tools` signature** (added to the `LLMClient` Protocol):

```python
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
    tool_calls: list[ToolCall]   # empty when the model is done

class LLMClient(Protocol):
    async def chat_with_tools(
        self,
        messages: list[ChatTurn],
        tools: list[ToolDef],
        *,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AssistantTurn: ...
```

`ChatTurn` mirrors the persisted shape (`role` + `content`/`tool_calls`/`tool_result`). Each provider adapter is a structural translator into its wire format — no orchestration logic.

**Loop** (`agent/chat.py::run_turn`):

```
1. Load full history for application_id.
2. Append the new user message; persist + emit {type:"message", role:"user"}.
3. For step in 1..MAX_STEPS (default 8):
     turn = await llm.chat_with_tools(history, TOOLS, system=SYSTEM_PROMPT)
     if not turn.tool_calls:
         persist assistant row (content=turn.text)
         emit {type:"message_delta", text:turn.text}
         emit {type:"message_done", id:<assistant_msg_id>}; return
     persist assistant row (content=turn.text, tool_calls=[...])
     for tc in turn.tool_calls:
         emit {type:"tool_call_start", id, name, arguments}
         try:    result = await TOOL_HANDLERS[tc.name](session, application_id, tc.arguments)
         except Exception as e:  result = {"error": str(e)}
         persist tool row; emit {type:"tool_call_result", id, name, result}
     # next loop iteration: history now includes the tool results
4. Loop fell through without a final assistant turn:
   emit {type:"error", phase:"agent", detail:"max iterations reached"}; return
```

Tool exceptions are **non-terminal**: the failure is wrapped as `{"error": str(...)}`, returned to the model as a normal tool result, and logged to `event_logs` (`event_type="chat.tool_failed"`). The loop continues so the model can recover.

LLM exceptions and the max-iter cap are **terminal**: emit a single `{type:"error"}` event, persist a synthetic assistant row (`content="(LLM error: …)"`), return. `message_done` is **not** emitted on a terminal error — the frontend treats `error` as a turn terminator.

Streaming is full-turn, not token-level. The progressive UX comes from tool-call cards arriving one at a time, not word-by-word typing. Token streaming is deferred to v1.1.

The endpoint always returns HTTP `200` once headers are flushed; errors are signaled in-stream so the user sees what happened. The conversation can continue with the next user message.

**Context window**: not actively managed in v1. With gpt-oss-120b's 128k context, hundreds of turns fit. Open question: truncate-oldest vs summarize when we hit it.

## Tool catalog

Tool handlers all receive `(session: AsyncSession, application_id: int, args: dict)`. `application_id` is implicit context from the request, never an LLM-supplied argument. JSON Schemas are declared in `agent/tools.py` and adapters convert them to each provider's shape.

### Reads

| Tool | Args | Returns |
|---|---|---|
| `get_candidate` | none | `{full_name, email, phone, location, headline, summary, skills, experience[], education[], links[]}` |
| `get_application` | none | `{stage, score, validated_at, invited_at, rejected_at, notes}` |
| `get_score_breakdown` | none | `{score, rationale, breakdown:[{criterion, weight, score, rationale}]}` |
| `get_job` | none | `{title, description, criteria[], status}` |
| `list_other_applications_for_candidate` | none | `[{application_id, job_title, stage, score, created_at}]` — same `candidate_id`, excludes self |

### Writes

| Tool | Args | Effect | Result returned to model |
|---|---|---|---|
| `save_note` | `{text: str}` | Appends a timestamped paragraph to `Application.notes` | `{ok: true, note_id}` |
| `validate_application` | `{notes?: str}` | Stage → `validated`, sets `validated_at`, optional notes appended | `{ok, previous_stage, undo_token}` |
| `reject_application` | `{reason: str}` | Stage → `rejected`, sets `rejected_at`, reason saved as note | `{ok, previous_stage, undo_token}` |

### Guardrails

- `validate_application` returns `{error:"stage X cannot move to validated"}` if current stage is `extracting` or `invited`. Same logic for `reject`.
- Reads are always safe; the loop deduplicates obvious double-fetches in the same turn (`(name, args)` cache).
- The agent cannot Notify; that boundary is preserved by simply not exposing the tool.

### Undo

`undo_token` is a UUID stored in an in-memory dict (15-min TTL) keyed to the previous stage and timestamp. The frontend's "Undo" button calls `POST /api/applications/{id}/undo` with the token; the backend reverts the stage if the token is fresh and current stage matches. Token refresh on server restart is acceptable (lost tokens just disable Undo for that turn).

### System prompt (drafted, refined during impl)

> You are a recruiting assistant helping {recruiter_name} evaluate {candidate_full_name} for {job_title}. You can read this candidate's data and the job's data, save notes for the recruiter, and validate or reject the candidate (both reversible until the recruiter sends an interview invitation). Do not make up facts — call tools when uncertain. Keep responses concise.

## API surface

### `POST /api/applications/{application_id}/chat`

Body: `{message: str}` (1–8000 chars).
Response: `200 OK` with `Content-Type: application/x-ndjson`, body is a stream of NDJSON events (one JSON object per line, newline-delimited, flushed after each line).

Errors:
- `404` — application not found.
- `409` — stage is `extracting` (no candidate data yet).
- `503` — LLM not configured (delegates to existing `get_llm` dep).

### `GET /api/applications/{application_id}/chat`

Returns `[ChatMessageRead]` ordered by `created_at`. Used by `useChat()` on first mount.

### `POST /api/applications/{application_id}/undo`

Body: `{undo_token: str}`. Reverses the stage change associated with the token (within 15 min). Returns the updated `ApplicationRead`. `410 Gone` if expired/unknown.

### NDJSON event taxonomy

```
{"type":"message",          "role":"user", "id":<msg_id>, "content":"..."}
{"type":"tool_call_start",  "id":"<tc_uuid>", "name":"validate_application", "arguments":{...}}
{"type":"tool_call_result", "id":"<tc_uuid>", "name":"...", "result":{...}}
{"type":"message_delta",    "text":"..."}                  # v1: single chunk per assistant turn
{"type":"message_done",     "id":<msg_id>}                  # final event for the turn
{"type":"error",            "detail":"...", "phase":"llm"|"tool"|"persist"|"agent"}
```

The `message` event for the user turn fires first so the UI can render the user bubble immediately even if the LLM call subsequently fails. `message_done` is always the terminal event on success.

## Frontend

### `hooks/use-chat.ts`

```ts
useChat(applicationId: number) {
  // Loads history with TanStack Query: GET /api/applications/{id}/chat
  // sendMessage(text): fetch POST, parse NDJSON via ReadableStream
  //   each parsed event mutates a draft message list in component state
  //   on message_done: invalidate the history query so canonical state reloads
  //   on error: keep the draft messages + show error banner
  return { messages, sendMessage, isStreaming, error, undo(token) };
}
```

NDJSON parser (`lib/ndjson.ts`, ~30 lines): read chunks, split on `\n`, JSON-parse each non-empty line, drop malformed lines with a `console.warn`. Generic over event payload type.

### `components/applications/chat-panel.tsx`

```
┌── Application detail page ────────────────────────────────┐
│  Profile + Score                       │  ChatPanel       │
│                                        │  ┌─────────────┐ │
│                                        │  │ messages    │ │
│                                        │  │  scroll ↓   │ │
│                                        │  ├─────────────┤ │
│                                        │  │ [textarea]  │ │
│                                        │  │ [Send]      │ │
│                                        │  └─────────────┘ │
└────────────────────────────────────────────────────────────┘
```

- **user** — right-aligned bubble.
- **assistant text** — left-aligned, markdown-rendered (existing `react-markdown` already a dep).
- **tool call** — collapsed card with `name(args)`, expandable to show JSON result. Auto-collapsed by default.
- **action result** (validate/reject) — tool card augmented with an **[Undo]** button; click hits `POST .../undo` and on success invalidates the application query so the kanban reflects the reverted stage.
- **empty state** — "Ask anything about this candidate." No canned suggestions in v1.
- **while streaming** — input disabled; latest assistant draft pulses subtly; tool-call cards animate in.
- **mobile** — chat opens as a full-screen modal triggered by a "Chat" button on the candidate detail header.

Theme: uses existing `bg-card` / `text-muted-foreground` / etc. from the dashboard; light + dark inherited free.

## Testing strategy

### Backend unit (pytest)

- `agent/tools.py` — each tool tested in isolation against a real Postgres testcontainer. Validate guardrails (e.g. `validate_application` rejects from stage `extracting`).
- `agent/chat.py` — agent loop tested with `FakeLLMClient` extended to support `chat_with_tools`: enqueue scripted `AssistantTurn` responses (with/without tool_calls), assert event sequence and persisted `ChatMessage` rows. Cover: zero-tool turn, multi-tool turn, max-iterations cap, tool failure, LLM exception.
- `llm/openai_compat.py::chat_with_tools` — `httpx.MockTransport`, assert request shape (tools array, `tool_choice="auto"`), parse a canned OpenAI-style `tool_calls` response.
- `llm/anthropic.py::chat_with_tools` — same with the existing Anthropic mock pattern.

### Backend API

- `POST /api/applications/{id}/chat` — assert NDJSON event sequence end-to-end with an injected `FakeLLMClient`. Test 404 / 409 / 503 paths.
- `POST /api/applications/{id}/undo` — undo within TTL succeeds; after TTL returns 410; unknown token 410.

### Frontend (Vitest + RTL + MSW)

- `useChat` — MSW returns canned NDJSON; assert messages array updates per event, error banner on `error`, `isStreaming` toggles.
- `ChatPanel` — scripted message list rendering: user bubble, assistant markdown, tool-call collapsed card, action card with Undo. Click Undo → MSW returns updated app → query invalidates.
- `lib/ndjson.ts` — parser handles split chunks (one JSON spread across two reads), trailing newlines, malformed lines (drop with warn).

### Manual smoke (added to `recruiter-frontend/SMOKE.md`)

1. Open a scored application → chat panel mounted, history empty.
2. "Summarize her async-Rust experience" → assistant text appears, no tools called.
3. "Validate her with note 'strong RustConf signal'" → tool_call card for `validate_application` renders, kanban moves to Validated, Undo button visible. Click Undo → kanban reverts.
4. Refresh page → entire conversation reloads from DB.
5. Kill backend mid-stream → frontend shows error banner; restart → next user message succeeds.

## Error handling

- **Network drop mid-stream** — frontend shows banner; user retries the message (turns are idempotent at the boundary because we persist the user message before calling the LLM, but a retry would create a duplicate user message — acceptable for v1; dedupe is a follow-up).
- **Tool exception** — caught in the loop; result is `{"error": str(...)}`; logged in `event_logs` with `event_type="chat.tool_failed"`.
- **LLM exception** — terminal `error` event, persisted assistant turn `(LLM error: …)`.
- **Stage race** (recruiter clicks "Validate" in UI while agent is mid-turn) — backend writes are last-write-wins; the agent will see the new stage on its next read. Conflicts surface as guardrail errors returned to the model.
- **Undo race** — if the recruiter changes stage manually after the agent moved it, the undo token validates against the *previous_stage* it saved, and refuses with 409 if current state has drifted. UI surfaces a toast.

## Open questions

Items deferred to implementation or v1.1:

- **Token-level streaming inside an assistant turn** — provider-specific SSE/`stream:true` plumbing; revisit if long answers feel sluggish.
- **Context-window strategy** — truncate-oldest vs summarize, pick when we approach 80k tokens.
- **Quick-prompt suggestions** — none in v1; revisit after dogfooding.
- **Multi-thread per application** — add `chat_thread_id` (nullable) when a real need surfaces.
- **Cross-candidate deep dive** — `list_other_applications_for_candidate` returns summaries; if the agent needs to read another application in detail, add `get_application_by_id(application_id)` with explicit arg.
- **Cost tracking** — chat turns aren't yet tied to `monthly_llm_spend_cap_usd`; plug in when the pipeline does.
- **`save_note` data model** — v1 appends to the existing `Application.notes` text field. If per-note timestamps + author become useful in the UI, split into a separate `notes` table.
- **Exact undo TTL** — 15 min is a placeholder; tune during impl.
- **System prompt wording** — drafted above, tuned during impl against gpt-oss-120b's behavior.

## Implementation phasing

Suggested order for the writing-plans pass:

1. `models/chat_message.py` + Alembic migration.
2. `LLMClient.chat_with_tools` Protocol + `FakeLLMClient` test extension.
3. `OpenAICompatLLMClient.chat_with_tools` (the one we'll actually run).
4. `agent/tools.py` — read tools first, then write tools with guardrails + undo store.
5. `agent/chat.py` — the loop.
6. `agent/events.py` + `api/chat.py` — NDJSON streaming endpoint + history GET + undo POST.
7. `AnthropicLLMClient.chat_with_tools` (parity, exercised when credits return).
8. Frontend: `lib/ndjson.ts` → `hooks/use-chat.ts` → `ChatPanel`.
9. Smoke + docs.
