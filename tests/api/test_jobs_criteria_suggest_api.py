# tests/api/test_jobs_criteria_suggest_api.py
import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.job_suggest import SuggestedCriteria, SuggestedCriterion


def _fake_with(items: list[tuple[str, float, str]]) -> FakeLLMClient:
    return FakeLLMClient(structured_responses=[
        SuggestedCriteria(criteria=[
            SuggestedCriterion(name=n, weight=w, description=d) for n, w, d in items
        ]),
    ])


@pytest.mark.asyncio
async def test_suggest_criteria_happy_path(api_client: AsyncClient) -> None:
    fake = _fake_with([
        ("A", 0.40, "x"), ("B", 0.30, "y"), ("C", 0.20, "z"), ("D", 0.10, "w"),
    ])
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        resp = await api_client.post(
            "/api/jobs/criteria/suggest",
            json={"title": "Backend", "description": "Build Rust APIs. " * 5},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["criteria"]) == 4
    weights = [c["weight"] for c in body["criteria"]]
    assert sum(weights) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_suggest_criteria_rejects_short_description(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(
            "/api/jobs/criteria/suggest",
            json={"title": "x", "description": "too short"},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 422  # Pydantic min_length=50


@pytest.mark.asyncio
async def test_suggest_criteria_returns_502_on_llm_failure(api_client: AsyncClient) -> None:
    # Empty FakeLLMClient → raises RuntimeError on first call.
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(
            "/api/jobs/criteria/suggest",
            json={"description": "x" * 80},
        )
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_suggest_criteria_requires_auth(api_client_unauth: AsyncClient) -> None:
    resp = await api_client_unauth.post(
        "/api/jobs/criteria/suggest",
        json={"description": "x" * 80},
    )
    assert resp.status_code == 401
