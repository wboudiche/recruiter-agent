from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recruiter.config import get_config
from recruiter.db import get_engine


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine(get_config().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def streaming_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Open a fresh DB session for use INSIDE a `StreamingResponse` body.

    The request-scoped `get_session` dep closes its session as soon as the
    handler returns — i.e., BEFORE the streaming generator runs. Streaming
    endpoints must therefore create their own session via this helper:

        async def streamer():
            async with streaming_session(engine) as session:
                ...
                yield serialize_event(...)
    """
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
