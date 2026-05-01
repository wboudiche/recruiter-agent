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
async def test_chat_stream_handles_client_disconnect(
    api_client: AsyncClient, with_fake_llm,
) -> None:
    """If the client closes the stream early, the streamer's per-request DB
    session must release cleanly and subsequent requests must still work.
    The user message persisted before the LLM call should still be visible
    in history (the orchestrator commits it before yielding the first event)."""
    app_id = await _create_scored_app(api_client)

    # Multi-event turn so there's content the client can disconnect mid-flight.
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="get_candidate", arguments={}),
        ]),
        AssistantTurn(text="answer", tool_calls=[]),
    ])

    # Open the stream, read just the first event (the user-message echo),
    # then exit the `async with` block — that triggers an httpx response
    # close, which cancels the streamer's async generator under FastAPI.
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "hello"},
    ) as r:
        first = None
        async for line in r.aiter_lines():
            if line:
                first = json.loads(line)
                break

    assert first is not None
    assert first["type"] == "message"
    assert first["content"] == "hello"

    # 1. Health endpoint still serves — engine pool is not broken.
    health = await api_client.get("/health")
    assert health.status_code == 200

    # 2. The user message persisted before disconnect.
    history = await api_client.get(f"/api/applications/{app_id}/chat")
    rows = history.json()
    assert any(r["role"] == "user" and r["content"] == "hello" for r in rows)

    # 3. Subsequent chat turn against the same application still works —
    #    no leftover transaction, no session leak.
    with_fake_llm._tool_turns.extend([AssistantTurn(text="follow-up", tool_calls=[])])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "again"},
    ) as r2:
        events = []
        async for line in r2.aiter_lines():
            if line:
                events.append(json.loads(line))
    types = [e["type"] for e in events]
    assert "message_done" in types


@pytest.mark.asyncio
async def test_chat_post_enforces_rate_limit(
    api_client: AsyncClient, with_fake_llm,
) -> None:
    """Hammering POST /chat past the configured limit returns 429."""
    from recruiter.api import rate_limit
    from recruiter.config import get_config

    cfg = get_config()
    original_limit = cfg.chat_rate_limit
    cfg.chat_rate_limit = "2/minute"
    # Reset SlowAPI's in-memory store so this test starts from zero.
    rate_limit.limiter.reset()

    try:
        app_id = await _create_scored_app(api_client)
        with_fake_llm._tool_turns.extend([
            AssistantTurn(text="ok1", tool_calls=[]),
            AssistantTurn(text="ok2", tool_calls=[]),
        ])

        # First two requests within the window: allowed.
        for _ in range(2):
            async with api_client.stream(
                "POST", f"/api/applications/{app_id}/chat",
                json={"message": "hi"},
            ) as r:
                assert r.status_code == 200
                async for _line in r.aiter_lines():
                    pass

        # Third within the same window: rate-limited.
        blocked = await api_client.post(
            f"/api/applications/{app_id}/chat", json={"message": "hi"},
        )
        assert blocked.status_code == 429
    finally:
        cfg.chat_rate_limit = original_limit
        rate_limit.limiter.reset()


@pytest.mark.asyncio
async def test_undo_410_for_unknown_token(api_client: AsyncClient, with_fake_llm) -> None:
    app_id = await _create_scored_app(api_client)
    r = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": "not-a-real-token"},
    )
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_undo_410_on_cross_app_token_preserves_token(
    api_client: AsyncClient, with_fake_llm,
) -> None:
    """A token issued for app A must NOT be consumed by an undo POST against app B."""
    app_a = await _create_scored_app(api_client)
    app_b = await _create_scored_app(api_client)

    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={}),
        ]),
        AssistantTurn(text="Done.", tool_calls=[]),
    ])
    token = None
    async with api_client.stream(
        "POST", f"/api/applications/{app_a}/chat",
        json={"message": "validate her"},
    ) as r:
        async for line in r.aiter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["type"] == "tool_call_result" and ev["name"] == "validate_application":
                token = ev["result"]["undo_token"]
    assert token is not None

    # Wrong app id — must 410 AND must not burn the token
    bad = await api_client.post(
        f"/api/applications/{app_b}/undo", json={"undo_token": token},
    )
    assert bad.status_code == 410

    # Right app id — token still works after the cross-app rejection
    good = await api_client.post(
        f"/api/applications/{app_a}/undo", json={"undo_token": token},
    )
    assert good.status_code == 200
    assert good.json()["stage"] == "scored"


@pytest.mark.asyncio
async def test_undo_restores_validated_at_after_revalidate(
    api_client: AsyncClient, with_fake_llm,
) -> None:
    """When the agent re-validates an already-validated app and the user undoes,
    validated_at must revert to the original timestamp, not be cleared and not
    leave the just-overwritten one in place."""
    app_id = await _create_scored_app(api_client)

    # First validate — captures a real validated_at
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="validate_application", arguments={}),
        ]),
        AssistantTurn(text="Done.", tool_calls=[]),
    ])
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "validate"},
    ) as r:
        async for _ in r.aiter_lines():
            pass

    first = await api_client.get(f"/api/applications/{app_id}")
    original_validated_at = first.json()["validated_at"]
    assert original_validated_at is not None

    # Second validate — re-stamps validated_at; agent issues a new undo token.
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t2", name="validate_application", arguments={}),
        ]),
        AssistantTurn(text="Re-validated.", tool_calls=[]),
    ])
    token = None
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "validate again"},
    ) as r:
        async for line in r.aiter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["type"] == "tool_call_result" and ev["name"] == "validate_application":
                token = ev["result"]["undo_token"]
    assert token is not None

    second = await api_client.get(f"/api/applications/{app_id}")
    new_validated_at = second.json()["validated_at"]
    assert new_validated_at != original_validated_at  # was overwritten

    # Undo should restore the ORIGINAL validated_at
    undo = await api_client.post(
        f"/api/applications/{app_id}/undo", json={"undo_token": token},
    )
    assert undo.status_code == 200
    body = undo.json()
    assert body["stage"] == "validated"  # we re-validated from validated → validated
    assert body["validated_at"] == original_validated_at
