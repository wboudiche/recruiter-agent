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
