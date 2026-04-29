import pytest
from sqlalchemy import text

from recruiter.db import get_engine


@pytest.mark.asyncio
async def test_engine_connects_and_runs_select_one(pg_dsn: str) -> None:
    engine = get_engine(pg_dsn)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()
