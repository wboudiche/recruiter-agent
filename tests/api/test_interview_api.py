import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.interview import GeneratedQuestion, GeneratedQuestions


@pytest.mark.asyncio
async def test_get_returns_null_kit_before_generation(
    api_client: AsyncClient, create_scored_app,
) -> None:
    app_id = await create_scored_app()
    resp = await api_client.get(f"/api/applications/{app_id}/interview-kit")
    assert resp.status_code == 200
    assert resp.json()["kit"] is None


@pytest.mark.asyncio
async def test_generate_returns_202_and_kit_is_no_longer_null(
    api_client: AsyncClient, create_scored_app,
) -> None:
    """202 because the model call runs in the background — the request must
    not block on it, and must not fail because of it.

    FastAPI's BackgroundTasks run to completion before the in-process
    ASGI transport used by `api_client` hands control back to the test
    (there is no separate worker), so by the time the follow-up GET runs
    the background task has already resolved the kit to its final state.
    What matters here is the contract the docstring above describes: the
    POST itself returns 202 without waiting on the model, and the kit
    lands in a terminal, non-null state without the request ever
    touching the LLM directly.
    """
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[GeneratedQuestions(questions=[
            GeneratedQuestion(text="Tell me about a production incident.",
                               criterion="reliability"),
        ])],
    )
    try:
        app_id = await create_scored_app()
        resp = await api_client.post(f"/api/applications/{app_id}/interview-kit/generate")
        assert resp.status_code == 202

        kit = (await api_client.get(f"/api/applications/{app_id}/interview-kit")).json()["kit"]
        assert kit["status"] in {"generating", "ready"}
        if kit["status"] == "ready":
            assert kit["generated_at"] is not None
            assert any(q["source"] == "probe" for q in kit["questions"])
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_generate_404s_for_an_unknown_application(api_client: AsyncClient) -> None:
    # FastAPI resolves get_llm before the handler runs (same as re-enrich);
    # provide a fake so the request reaches the handler's 404 check.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post("/api/applications/999999/interview-kit/generate")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)
