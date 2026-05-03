import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.agent.tools import TOOLS, ToolContext, get_tool_handler
from recruiter.agent.undo import InMemoryUndoStore, UndoStore
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


def _ctx(session: AsyncSession, application_id: int, undo_store: UndoStore | None = None) -> ToolContext:
    return ToolContext(
        session=session,
        application_id=application_id,
        undo_store=undo_store or InMemoryUndoStore(ttl_seconds=60),
    )


@pytest.mark.asyncio
async def test_get_candidate(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    handler = get_tool_handler("get_candidate")
    result = await handler(_ctx(db_session_with_schema, app_id), {})
    assert result["full_name"] == "Marie Lefèvre"
    assert result["email"] == "m@example.com"
    assert "Rust" in result["skills"]
    assert result["experience"][0]["company"] == "Datadome"


@pytest.mark.asyncio
async def test_get_application(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_application")(_ctx(db_session_with_schema, app_id), {})
    assert result["stage"] == "scored"
    assert result["score"] == 92
    assert result["validated_at"] is None


@pytest.mark.asyncio
async def test_get_score_breakdown(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_score_breakdown")(_ctx(db_session_with_schema, app_id), {})
    assert result["score"] == 92
    assert result["rationale"] == "strong"
    assert result["breakdown"][0]["criterion"] == "rust"


@pytest.mark.asyncio
async def test_get_job(db_session_with_schema: AsyncSession) -> None:
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("get_job")(_ctx(db_session_with_schema, app_id), {})
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
        _ctx(db_session_with_schema, app_id), {}
    )
    assert len(result) == 1
    assert result[0]["application_id"] == app2.id
    assert result[0]["job_title"] == "DevOps"
    assert result[0]["stage"] == "extracting"


def test_tools_registry_lists_all_tools() -> None:
    names = [t.name for t in TOOLS]
    expected = {"get_candidate", "get_application", "get_score_breakdown", "get_job",
                "list_other_applications_for_candidate", "save_note",
                "validate_application", "reject_application",
                "search_linkedin", "search_github", "search_web"}
    assert set(names) == expected
    assert len(names) == 11


@pytest.mark.asyncio
async def test_save_note_appends_to_application_notes(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    result = await get_tool_handler("save_note")(
        _ctx(db_session_with_schema, app_id), {"text": "promising candidate"}
    )
    assert result["ok"] is True
    app = await db_session_with_schema.get(Application, app_id)
    assert app.notes is not None
    assert "promising candidate" in app.notes


@pytest.mark.asyncio
async def test_save_note_appends_with_timestamp(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    ctx = _ctx(db_session_with_schema, app_id)
    await get_tool_handler("save_note")(ctx, {"text": "first"})
    await get_tool_handler("save_note")(ctx, {"text": "second"})
    app = await db_session_with_schema.get(Application, app_id)
    assert "first" in app.notes
    assert "second" in app.notes
    # both notes preserved
    assert app.notes.index("first") < app.notes.index("second")


@pytest.mark.asyncio
async def test_validate_from_scored_succeeds(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    store = InMemoryUndoStore(ttl_seconds=60)
    result = await get_tool_handler("validate_application")(
        _ctx(db_session_with_schema, app_id, undo_store=store), {"notes": "looks great"},
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
        _ctx(db_session_with_schema, app_id), {},
    )
    assert "error" in result
    assert "extracting" in result["error"].lower()


@pytest.mark.asyncio
async def test_reject_from_scored_succeeds(db_session_with_schema):
    app_id = await _seed(db_session_with_schema)
    store = InMemoryUndoStore(ttl_seconds=60)
    result = await get_tool_handler("reject_application")(
        _ctx(db_session_with_schema, app_id, undo_store=store), {"reason": "no Rust experience"},
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
        _ctx(db_session_with_schema, app_id), {"reason": "x"},
    )
    assert "error" in result
    assert "invited" in result["error"].lower()


def test_tools_registry_matches_handlers() -> None:
    """Drift guard: every TOOLS entry must have a corresponding registered handler."""
    from recruiter.agent.tools import TOOLS, _HANDLERS
    assert {t.name for t in TOOLS} == set(_HANDLERS.keys())
