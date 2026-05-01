import json

import pytest
from httpx import AsyncClient

from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app


@pytest.fixture
def fake_llm():
    return FakeLLMClient(tool_turn_responses=[])


@pytest.fixture
def with_fake_llm(fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    try:
        yield fake_llm
    finally:
        app.dependency_overrides.pop(get_llm, None)


async def _create_scored_app(api_client: AsyncClient) -> int:
    job = await api_client.post("/api/jobs", json={
        "title": "Backend", "description": "x", "criteria": []
    })
    job_id = job.json()["id"]
    from recruiter.api.candidates import get_engine_dep
    engine = app.dependency_overrides[get_engine_dep]()
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from recruiter.models import Application, Candidate, Stage
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        c = Candidate(source_type="paste", full_name="Marie", email="m@example.com")
        session.add(c); await session.flush()
        a = Application(job_id=job_id, candidate_id=c.id, stage=Stage.SCORED, score=80)
        session.add(a); await session.commit()
        return a.id


@pytest.mark.asyncio
async def test_chat_post_streams_ndjson(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text="Hello.", tool_calls=[]),
    ])

    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "hi"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = []
        async for line in r.aiter_lines():
            if line:
                events.append(json.loads(line))

    assert [e["type"] for e in events] == ["message", "message_delta", "message_done"]


@pytest.mark.asyncio
async def test_chat_get_history_returns_persisted_messages(api_client, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([AssistantTurn(text="ok", tool_calls=[])])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "hi"},
    ) as r:
        async for _ in r.aiter_lines():
            pass

    history = await api_client.get(f"/api/applications/{app_id}/chat")
    assert history.status_code == 200
    payload = history.json()
    assert len(payload) == 2
    assert payload[0]["role"] == "user" and payload[0]["content"] == "hi"
    assert payload[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_chat_post_409_when_extracting(api_client: AsyncClient, with_fake_llm) -> None:
    job = await api_client.post("/api/jobs", json={
        "title": "x", "description": "x", "criteria": []
    })
    job_id = job.json()["id"]
    from recruiter.api.candidates import get_engine_dep
    engine = app.dependency_overrides[get_engine_dep]()
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from recruiter.models import Application, Candidate, Stage
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        c = Candidate(source_type="paste"); session.add(c); await session.flush()
        a = Application(job_id=job_id, candidate_id=c.id, stage=Stage.EXTRACTING)
        session.add(a); await session.commit()
        app_id = a.id

    r = await api_client.post(f"/api/applications/{app_id}/chat", json={"message": "hi"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_chat_post_404_when_app_missing(api_client, with_fake_llm) -> None:
    r = await api_client.post("/api/applications/99999/chat", json={"message": "hi"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_undo_reverses_stage_within_ttl(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={}),
        ]),
        AssistantTurn(text="Done.", tool_calls=[]),
    ])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "validate her"},
    ) as r:
        token = None
        async for line in r.aiter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["type"] == "tool_call_result" and ev["name"] == "validate_application":
                token = ev["result"]["undo_token"]

    assert token is not None
    undo = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": token},
    )
    assert undo.status_code == 200
    assert undo.json()["stage"] == "scored"


@pytest.mark.asyncio
async def test_undo_410_for_unknown_token(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    r = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": "not-a-real-token"},
    )
    assert r.status_code == 410
