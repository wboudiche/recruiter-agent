import asyncio
from email import message_from_bytes

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.api.notifications import get_smtp_factory
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


class FakeSmtp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str], bytes]] = []

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        pass

    def sendmail(self, sender: str, to: list[str], data: bytes) -> None:
        self.sent.append((sender, to, data))


@pytest.mark.asyncio
async def test_smtp_notify_sends_email_and_advances_stage(api_client: AsyncClient) -> None:
    instance = FakeSmtp()
    app.dependency_overrides[get_smtp_factory] = lambda: (lambda h, p: instance)

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[
                    ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")
                ],
                rationale="ok",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
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
            await api_client.post(
                "/api/jobs", json={"title": "Rust role", "description": "D", "criteria": []}
            )
        ).json()["id"]
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates",
                json={"kind": "paste", "content": "Alice — Rust"},
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
                "subject": "Interview at Acme",
                "body": "Hi Alice, here are some times.",
                "slots": [
                    {
                        "start": "2026-05-01T10:00:00+00:00",
                        "end": "2026-05-01T11:00:00+00:00",
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "notification_id" in body
        assert "external_id" in body

        r = await api_client.get(f"/api/applications/{app_id}")
        assert r.json()["stage"] == "invited"
        assert r.json()["invited_at"] is not None

        assert len(instance.sent) == 1
        sender, to, data = instance.sent[0]
        assert sender == "me@example.com"
        assert to == ["alice@example.com"]
        msg = message_from_bytes(data)
        assert msg["Subject"] == "Interview at Acme"
        types = [p.get_content_type() for p in msg.walk()]
        assert "text/calendar" in types
    finally:
        app.dependency_overrides.pop(get_smtp_factory, None)
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_smtp_notify_503_when_smtp_not_configured(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com"),
            ScoreResult(
                score=70,
                breakdown=[
                    ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")
                ],
                rationale="ok",
            ),
        ]
    )
    try:
        job_id = (
            await api_client.post(
                "/api/jobs", json={"title": "T", "description": "D", "criteria": []}
            )
        ).json()["id"]
        app_id = (
            await api_client.post(
                f"/api/jobs/{job_id}/candidates",
                json={"kind": "paste", "content": "Alice"},
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
                "subject": "x",
                "body": "x",
                "slots": [
                    {"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}
                ],
            },
        )
        assert resp.status_code == 503
        assert "SMTP" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
