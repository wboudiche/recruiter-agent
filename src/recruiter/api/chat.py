from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from recruiter.agent.chat import run_turn
from recruiter.agent.events import error_event, serialize_event
from recruiter.agent.undo import UndoStore, get_default_undo_store
from recruiter.api.candidates import get_engine_dep, get_llm
from recruiter.api.deps import get_session, streaming_session
from recruiter.api.rate_limit import chat_rate_limit, limiter
from recruiter.llm.client import LLMClient
from recruiter.models import Application, ChatMessage, Stage
from recruiter.schemas.application import ApplicationRead
from recruiter.schemas.chat import ChatMessageRead, ChatRequest, UndoRequest

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
@limiter.limit(chat_rate_limit)
async def post_chat(
    request: Request,  # required by SlowAPI's decorator to read remote IP
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

    async def streamer() -> AsyncIterator[bytes]:
        async with streaming_session(engine) as own_session:
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
    consumed = undo_store.consume(payload.undo_token, application_id=application_id)
    if consumed is None:
        raise HTTPException(status_code=410, detail="undo token expired or unknown")

    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    previous_stage = consumed["previous_stage"]
    if previous_stage not in _UNDO_ALLOWED_STAGES:
        # Defensive: a token from a future code path that revives a stage we
        # don't currently allow undoing into. Refuse rather than silently set
        # the stage to something the rest of the system won't expect.
        raise HTTPException(status_code=410, detail="undo target stage no longer allowed")

    app_row.stage = Stage(previous_stage)
    # Restore the timestamps the tool snapshotted at issue time. Falls back to
    # the legacy behavior for tokens issued before the snapshot was added.
    if "previous_validated_at" in consumed:
        app_row.validated_at = _parse_iso(consumed["previous_validated_at"])
    elif previous_stage != "validated":
        app_row.validated_at = None
    if "previous_rejected_at" in consumed:
        app_row.rejected_at = _parse_iso(consumed["previous_rejected_at"])
    elif previous_stage != "rejected":
        app_row.rejected_at = None
    app_row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(app_row)
    return ApplicationRead.model_validate(app_row)


_UNDO_ALLOWED_STAGES = {"scored", "validated", "rejected"}


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
