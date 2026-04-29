import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

Listener = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._lock = asyncio.Lock()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                await fn(event)
            except Exception:
                pass
