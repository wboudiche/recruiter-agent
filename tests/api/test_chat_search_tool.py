import json

import pytest
from httpx import AsyncClient

from recruiter.agent.types import AssistantTurn, ToolCall
from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.sourcing.provider import SearchResult


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
    """Mirror the helper in test_chat_api.py — create a candidate +
    SCORED application directly via the engine."""
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


class _StubProvider:
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                name="Alice", url="https://www.linkedin.com/in/alice/",
                snippet="Rust dev", source="web",
            ),
        ]


@pytest.mark.asyncio
async def test_chat_search_linkedin_emits_tool_search_results_event(
    api_client: AsyncClient, with_fake_llm, monkeypatch,
) -> None:
    """End-to-end: user chats → LLM emits tool_use(search_linkedin) → tool
    handler runs against a stubbed provider → NDJSON stream carries the
    structured tool.search_results event."""
    # Stub provider.resolve so the search tool gets our fake provider.
    import recruiter.sourcing.provider as provider_mod
    monkeypatch.setattr(provider_mod, "resolve", lambda _settings: _StubProvider())

    app_id = await _create_scored_app(api_client)

    # Seed a SettingsRow so _load_settings_for_tool returns non-None — the
    # tool short-circuits to "not configured" otherwise. The actual fields
    # don't matter because provider.resolve is monkeypatched above.
    from recruiter.api.candidates import get_engine_dep
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from recruiter.models import SettingsRow
    engine = app.dependency_overrides[get_engine_dep]()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        session.add(SettingsRow(id=1, search_provider="google_cse"))
        await session.commit()

    # Two LLM turns: tool call, then final text.
    with_fake_llm._tool_turns.extend([
        AssistantTurn(text=None, tool_calls=[
            ToolCall(id="t1", name="search_linkedin",
                     arguments={"query": "rust dev", "limit": 2}),
        ]),
        AssistantTurn(text="Found candidates.", tool_calls=[]),
    ])

    events: list[dict] = []
    async with api_client.stream(
        "POST", f"/api/applications/{app_id}/chat",
        json={"message": "find me rust devs"},
    ) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line:
                events.append(json.loads(line))

    types = [e["type"] for e in events]
    assert "tool.search_results" in types, (
        f"expected tool.search_results in stream, got types={types}"
    )
    sr = next(e for e in events if e["type"] == "tool.search_results")
    assert sr["tool_name"] == "search_linkedin"
    assert sr["source"] == "linkedin"
    assert sr["results"][0]["name"] == "Alice"
    assert sr["results"][0]["url"] == "https://www.linkedin.com/in/alice/"
    # Per-card source overridden by the tool wrapper.
    assert sr["results"][0]["source"] == "linkedin"
    # Stream order: tool_call_result must come BEFORE tool.search_results.
    types_minus_messages = [t for t in types if t in {"tool_call_result", "tool.search_results"}]
    assert types_minus_messages == ["tool_call_result", "tool.search_results"], (
        f"expected tool_call_result before tool.search_results, got {types_minus_messages}"
    )
