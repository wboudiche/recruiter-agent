from datetime import datetime, timezone

import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, Slot


@pytest.mark.asyncio
async def test_draft_email_returns_subject_body_with_slots_in_prompt() -> None:
    candidate = ExtractedCandidate(full_name="Alice Doe", skills=["Rust"])
    slots = [
        Slot(
            start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
        )
    ]
    fake = FakeLLMClient(
        structured_responses=[
            DraftedEmail(subject="Interview at Acme — Rust role", body="Hi Alice...")
        ]
    )
    result = await draft_email(
        recruiter_name="Walid",
        recruiter_email="walid@acme.com",
        company="Acme",
        job_title="Senior Rust Engineer",
        candidate=candidate,
        slots=slots,
        llm=fake,
    )
    assert result.subject.startswith("Interview at Acme")
    assert result.body.startswith("Hi")

    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Alice" in user_msg.content
    assert "Rust" in user_msg.content
    assert "2026-05-01" in user_msg.content
