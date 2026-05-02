import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from recruiter.api.candidates import get_event_bus
from recruiter.api.deps import require_user
from recruiter.events import EventBus

router = APIRouter(prefix="/api", tags=["events"], dependencies=[Depends(require_user)])


@router.get("/events")
async def stream_events(bus: EventBus = Depends(get_event_bus)) -> EventSourceResponse:
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def listener(event: dict) -> None:
        await queue.put(event)

    unsubscribe = bus.subscribe(listener)

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                event = await queue.get()
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
        finally:
            unsubscribe()

    return EventSourceResponse(event_generator())
