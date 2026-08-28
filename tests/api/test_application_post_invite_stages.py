import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.api.notifications import get_smtp_factory
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


class FakeSmtp:
    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        pass

    def sendmail(self, sender: str, to: list[str], data: bytes) -> None:
        pass


async def _seed_invited_application(api_client: AsyncClient) -> int:
    app.dependency_overrides[get_smtp_factory] = lambda: (lambda h, p: FakeSmtp())
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com"),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=85, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    await api_client.put(
        "/api/settings",
        json={
            "smtp_config": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "me@example.com",
                "password": "pw",
                "from_email": "me@example.com",
            }
        },
    )
    job_id = (
        await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
    ).json()["id"]
    app_id = (
        await api_client.post(
            f"/api/jobs/{job_id}/candidates", json={"kind": "paste", "content": "Alice"}
        )
    ).json()["application_id"]
    for _ in range(50):
        await asyncio.sleep(0.05)
        r = await api_client.get(f"/api/applications/{app_id}")
        if r.json()["stage"] == "scored":
            break
    await api_client.patch(f"/api/applications/{app_id}", json={"stage": "validated"})
    resp = await api_client.post(
        f"/api/applications/{app_id}/notify",
        json={
            "channel": "smtp",
            "subject": "Interview",
            "body": "Hi",
            "slots": [
                {"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    return app_id


@pytest.mark.asyncio
async def test_forward_chain_scheduled_through_hired(api_client: AsyncClient) -> None:
    try:
        app_id = await _seed_invited_application(api_client)

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "scheduled"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "scheduled"
        assert resp.json()["scheduled_at"] is not None

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "interviewed"
        assert resp.json()["interviewed_at"] is not None

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "offer"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "offer"
        assert resp.json()["offer_at"] is not None

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "hired"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "hired"
        assert resp.json()["hired_at"] is not None
    finally:
        app.dependency_overrides.pop(get_smtp_factory, None)
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_cannot_skip_a_stage(api_client: AsyncClient) -> None:
    """invited -> interviewed directly (skipping scheduled) is rejected,
    distinctly from the 422 an unrecognized stage literal would give."""
    try:
        app_id = await _seed_invited_application(api_client)
        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "interviewed"})
        assert resp.status_code == 409, resp.text
    finally:
        app.dependency_overrides.pop(get_smtp_factory, None)
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_hired_is_fully_terminal(api_client: AsyncClient) -> None:
    try:
        app_id = await _seed_invited_application(api_client)
        for stage in ["scheduled", "interviewed", "offer", "hired"]:
            resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": stage})
            assert resp.status_code == 200, resp.text

        resp = await api_client.patch(f"/api/applications/{app_id}", json={"stage": "rejected"})
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_smtp_factory, None)
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_reject_allowed_from_scheduled_interviewed_offer(api_client: AsyncClient) -> None:
    try:
        for target_before_reject in ["scheduled", "interviewed", "offer"]:
            app_id = await _seed_invited_application(api_client)
            chain = ["scheduled", "interviewed", "offer"]
            for stage in chain[: chain.index(target_before_reject) + 1]:
                step = await api_client.patch(
                    f"/api/applications/{app_id}", json={"stage": stage}
                )
                assert step.status_code == 200, step.text

            resp = await api_client.patch(
                f"/api/applications/{app_id}",
                json={"stage": "rejected", "rejection_reason": "no longer interested"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["stage"] == "rejected"
    finally:
        app.dependency_overrides.pop(get_smtp_factory, None)
        app.dependency_overrides.pop(get_llm, None)
