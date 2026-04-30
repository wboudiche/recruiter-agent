from datetime import datetime, timezone

from icalendar import Calendar

from recruiter.notifications.ics import build_ics
from recruiter.schemas.notification import Slot


def test_build_ics_produces_one_event_per_slot() -> None:
    slots = [
        Slot(
            start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        Slot(
            start=datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, 15, 0, tzinfo=timezone.utc),
        ),
    ]
    data = build_ics(
        summary="Interview with Acme",
        description="Looking forward to chatting.",
        slots=slots,
        organizer_email="me@example.com",
        attendee_email="alice@example.com",
    )
    cal = Calendar.from_ical(data)
    events = [c for c in cal.walk("VEVENT")]
    assert len(events) == 2
    assert all("SUMMARY" in e for e in events)
    assert all(b"alice@example.com" in c.to_ical() for c in events)


def test_build_ics_returns_bytes() -> None:
    slot = Slot(
        start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
    )
    data = build_ics(
        summary="x",
        description="x",
        slots=[slot],
        organizer_email="me@example.com",
        attendee_email="alice@example.com",
    )
    assert isinstance(data, bytes)
    assert data.startswith(b"BEGIN:VCALENDAR")
