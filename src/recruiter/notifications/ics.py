import uuid
from datetime import datetime, timezone

from icalendar import Calendar, Event, vCalAddress

from recruiter.schemas.notification import Slot


def build_ics(
    *,
    summary: str,
    description: str,
    slots: list[Slot],
    organizer_email: str,
    attendee_email: str,
) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//recruiter-agent//EN")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST")

    organizer = vCalAddress(f"MAILTO:{organizer_email}")
    organizer.params["cn"] = organizer_email

    attendee = vCalAddress(f"MAILTO:{attendee_email}")
    attendee.params["cn"] = attendee_email
    attendee.params["role"] = "REQ-PARTICIPANT"
    attendee.params["partstat"] = "NEEDS-ACTION"
    attendee.params["rsvp"] = "TRUE"

    for slot in slots:
        event = Event()
        event.add("uid", f"{uuid.uuid4()}@recruiter-agent")
        event.add("summary", summary)
        event.add("description", description)
        event.add("dtstart", slot.start)
        event.add("dtend", slot.end)
        event.add("dtstamp", datetime.now(timezone.utc))
        event["organizer"] = organizer
        event.add("attendee", attendee, encode=False)
        cal.add_component(event)

    return cal.to_ical()
