from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recruiter.config import get_config
from recruiter.db import get_engine


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine(get_config().database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
