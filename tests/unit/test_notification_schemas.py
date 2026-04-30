from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from recruiter.schemas.notification import DraftedEmail, NotifyPayload, Slot


def test_slot_validates_end_after_start() -> None:
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)
    Slot(start=start, end=end)
    with pytest.raises(ValidationError):
        Slot(start=end, end=start)


def test_notify_payload_requires_at_least_one_slot() -> None:
    NotifyPayload(
        channel="smtp",
        subject="Interview",
        body="Hi",
        slots=[
            Slot(
                start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
                end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
            )
        ],
    )
    with pytest.raises(ValidationError):
        NotifyPayload(channel="smtp", subject="Interview", body="Hi", slots=[])


def test_drafted_email_shape() -> None:
    d = DraftedEmail(subject="Hi Alice", body="...")
    assert d.subject == "Hi Alice"
