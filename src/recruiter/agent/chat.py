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
from recruiter.models import Application, Candidate, ChatMessage, Job, MessageRole, SettingsRow

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
    yield message_event(role="user", id=user_row.id, content=user_message)

    # 2. Build system prompt + history
    try:
        system = await _build_system_prompt(session, application_id)
    except Exception as exc:
        yield error_event(detail=f"failed to load context: {exc}", phase="persist")
        return

    # 3. Loop
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
