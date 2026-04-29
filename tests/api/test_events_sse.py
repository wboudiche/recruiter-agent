import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_event_bus, get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


@pytest.mark.asyncio
async def test_sse_emits_stage_events_during_pipeline(api_client: AsyncClient) -> None:
    job_id = (await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})).json()["id"]

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", skills=["Rust"]),
            ScoreResult(score=70, breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")], rationale="ok"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        bus = get_event_bus()
        events: list[dict] = []

        async def listener(payload: dict) -> None:
            events.append(payload)

        unsub = bus.subscribe(listener)
        try:
            create = await api_client.post(
                f"/api/jobs/{job_id}/candidates",
                json={"kind": "paste", "content": "Alice"},
            )
            application_id = create.json()["application_id"]

            for _ in range(50):
                await asyncio.sleep(0.05)
                if any(e.get("stage") == "scored" for e in events):
                    break
        finally:
            unsub()

        stages = [e["stage"] for e in events if e.get("type") == "stage"]
        assert "extracting" in stages
        assert "scored" in stages
    finally:
        app.dependency_overrides.pop(get_llm, None)
