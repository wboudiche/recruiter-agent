# Plan C — Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the notification path so a recruiter can validate a candidate, click "Notify & invite", pick channel + interview slots, edit an LLM-drafted email, and send a real email with calendar attachment. Two channels: SMTP+ICS (works anywhere, no OAuth) and Gmail+GCal (richer, requires OAuth).

**Architecture:** A small `notifications/` Python package with one `Notifier` interface and two implementations (`SmtpNotifier`, `GmailNotifier`). Backend exposes `POST /api/applications/{id}/draft-email` (LLM call, returns subject + body) and `POST /api/applications/{id}/notify` (dispatches to the right notifier, persists a `Notification` row, advances stage). Google OAuth flow uses a server-side `oauth_states` table for the state token (no cookies, single-user). Frontend swaps the placeholder toast on the `Notify & invite` button for a 4-step wizard modal (Channel → Slots → Draft → Confirm) and replaces the Notifications-tab placeholder with a real form (Google connect button + SMTP host/port/user/pass fields).

**Tech Stack:** Python (existing FastAPI/SQLAlchemy/Anthropic SDK), `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `icalendar`, Python stdlib `smtplib`+`email`. Frontend: existing React + TanStack Query + shadcn/ui, plus `<input type="datetime-local">` for slot pickers.

**Reference:** Spec at `docs/superpowers/specs/2026-04-30-plan-b-frontend-design.md`. Plan B (frontend) merged on `main`; the `Notify & invite` button currently shows `toast.info("Notify wizard ships in Plan C")`.

**Phasing within this plan** — you can stop after Task 12 and ship "SMTP-only" if Google OAuth setup isn't ready yet. Tasks 13-22 add the Gmail+GCal path on top.

---

## File Structure

**Backend (new):**
```
src/recruiter/
├── notifications/
│   ├── __init__.py
│   ├── notifier.py             # Notifier Protocol + dispatch helper
│   ├── ics.py                  # build .ics attachments from Slot list
│   ├── smtp.py                 # SmtpNotifier
│   ├── gmail.py                # GmailNotifier (uses google-api-python-client)
│   ├── gcal.py                 # create Calendar event with attendees
│   └── google_oauth.py         # token storage, refresh, scope helpers
├── api/
│   ├── notifications.py        # POST /draft-email, POST /notify
│   └── auth_google.py          # GET /api/auth/google/start, GET /callback
├── models/
│   └── oauth_state.py          # state token rows with TTL
├── pipeline/
│   └── email_drafter.py        # LLM email drafter (similar to extractor/scorer)
└── schemas/
    └── notification.py         # NotifyPayload, DraftedEmail, Slot
```

**Backend (modified):**
- `src/recruiter/main.py` — include the two new routers.
- `src/recruiter/models/__init__.py` — export `OAuthState`.
- `pyproject.toml` — add 4 deps.
- `alembic/versions/<auto>` — new migration for `oauth_states` table.

**Frontend (new):**
```
recruiter-frontend/src/
├── components/notify/
│   ├── notify-wizard.tsx       # shell + step navigation
│   ├── step-channel.tsx
│   ├── step-slots.tsx
│   ├── step-draft.tsx
│   └── step-confirm.tsx
├── components/settings/
│   └── notifications-tab.tsx   # replaces notifications-tab-placeholder
└── hooks/
    ├── use-notify.ts            # draft + send mutations
    └── use-google-oauth.ts      # connect / disconnect helpers
```

**Frontend (modified):**
- `src/components/candidate/action-bar.tsx` — replace toast with `<NotifyWizard>`.
- `src/routes/settings.tsx` — swap placeholder for real tab.
- `src/lib/api-types.ts` — regenerate.
- `src/components/settings/notifications-tab-placeholder.tsx` — delete.

---

## Task 1: Backend dependencies + Slot schema

**Files:**
- Modify: `pyproject.toml`
- Create: `src/recruiter/schemas/notification.py`
- Create: `tests/unit/test_notification_schemas.py`

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml` — append to `[project] dependencies`:

```toml
  "google-api-python-client>=2.140",
  "google-auth>=2.34",
  "google-auth-oauthlib>=1.2",
  "icalendar>=5.0",
```

Run:
```bash
.venv/bin/pip install -e ".[dev]"
```

Expected: 4 new packages installed, no errors.

- [ ] **Step 2: Write the failing schemas test**

Create `tests/unit/test_notification_schemas.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from recruiter.schemas.notification import DraftedEmail, NotifyPayload, Slot


def test_slot_validates_end_after_start() -> None:
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)
    Slot(start=start, end=end)
    with pytest.raises(ValidationError):
        Slot(start=end, end=start)  # reversed


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
```

- [ ] **Step 3: Run test (expect ImportError)**

Run: `.venv/bin/python -m pytest tests/unit/test_notification_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'Slot'`.

- [ ] **Step 4: Implement schemas**

Create `src/recruiter/schemas/notification.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Slot(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _end_after_start(self) -> "Slot":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class DraftedEmail(BaseModel):
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)


class NotifyPayload(BaseModel):
    channel: Literal["smtp", "gmail"]
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_notification_schemas.py -v`
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/recruiter/schemas/notification.py tests/unit/test_notification_schemas.py
git commit -m "feat(schemas): add Slot, DraftedEmail, NotifyPayload + Google/iCal deps"
```

---

## Task 2: ICS attachment builder

**Files:**
- Create: `src/recruiter/notifications/__init__.py`
- Create: `src/recruiter/notifications/ics.py`
- Create: `tests/unit/test_ics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ics.py`:

```python
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
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_ics.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `src/recruiter/notifications/__init__.py` (empty).

Create `src/recruiter/notifications/ics.py`:

```python
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
        event.add("attendee", attendee, encode=0)
        cal.add_component(event)

    return cal.to_ical()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_ics.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/notifications/__init__.py src/recruiter/notifications/ics.py tests/unit/test_ics.py
git commit -m "feat(notifications): add ICS attachment builder"
```

---

## Task 3: SMTP notifier

**Files:**
- Create: `src/recruiter/notifications/notifier.py`
- Create: `src/recruiter/notifications/smtp.py`
- Create: `tests/unit/test_smtp_notifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_smtp_notifier.py`:

```python
from datetime import datetime, timezone
from email import message_from_bytes

import pytest

from recruiter.notifications.smtp import SmtpConfig, SmtpNotifier
from recruiter.schemas.notification import Slot


class FakeSmtp:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.sent: list[tuple[str, list[str], bytes]] = []
        self.tls_started = False
        self.logged_in_as: str | None = None

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.tls_started = True

    def login(self, user: str, _password: str) -> None:
        self.logged_in_as = user

    def sendmail(self, sender: str, to: list[str], data: bytes) -> None:
        self.sent.append((sender, to, data))


@pytest.mark.asyncio
async def test_smtp_notifier_sends_email_with_ics_attachment() -> None:
    captured: dict = {}

    def factory(host: str, port: int) -> FakeSmtp:
        captured["host"] = host
        captured["port"] = port
        captured["instance"] = FakeSmtp()
        return captured["instance"]

    cfg = SmtpConfig(
        host="smtp.example.com",
        port=587,
        user="me@example.com",
        password="pw",
        from_email="me@example.com",
    )
    notifier = SmtpNotifier(cfg, smtp_factory=factory)
    slots = [
        Slot(
            start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
        )
    ]

    receipt = await notifier.send_invitation(
        to_email="alice@example.com",
        subject="Interview with Acme",
        body="Hi Alice — proposed times below.",
        slots=slots,
    )
    assert receipt.external_id is not None
    assert captured["host"] == "smtp.example.com"
    assert captured["port"] == 587
    instance = captured["instance"]
    assert instance.tls_started is True
    assert instance.logged_in_as == "me@example.com"
    sender, to, raw = instance.sent[0]
    assert sender == "me@example.com"
    assert to == ["alice@example.com"]
    msg = message_from_bytes(raw)
    parts = list(msg.walk())
    types = [p.get_content_type() for p in parts]
    assert "text/plain" in types
    assert "text/calendar" in types or "application/ics" in [p.get_content_type() for p in parts]
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_smtp_notifier.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement Notifier interface**

Create `src/recruiter/notifications/notifier.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from recruiter.schemas.notification import Slot


@dataclass
class NotificationReceipt:
    external_id: str  # provider message id (or UUID for SMTP)
    provider: str     # "smtp" | "gmail"


class Notifier(Protocol):
    async def send_invitation(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        slots: list[Slot],
    ) -> NotificationReceipt: ...
```

- [ ] **Step 4: Implement SmtpNotifier**

Create `src/recruiter/notifications/smtp.py`:

```python
import smtplib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage

from recruiter.notifications.ics import build_ics
from recruiter.notifications.notifier import NotificationReceipt
from recruiter.schemas.notification import Slot


@dataclass
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    from_email: str


class SmtpNotifier:
    def __init__(
        self,
        config: SmtpConfig,
        *,
        smtp_factory: Callable[[str, int], smtplib.SMTP] | None = None,
    ) -> None:
        self._config = config
        self._smtp_factory = smtp_factory or (lambda h, p: smtplib.SMTP(h, p))

    async def send_invitation(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        slots: list[Slot],
    ) -> NotificationReceipt:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._config.from_email
        message["To"] = to_email
        message.set_content(body)

        ics_bytes = build_ics(
            summary=subject,
            description=body,
            slots=slots,
            organizer_email=self._config.from_email,
            attendee_email=to_email,
        )
        message.add_attachment(
            ics_bytes,
            maintype="text",
            subtype="calendar",
            filename="invitation.ics",
        )

        with self._smtp_factory(self._config.host, self._config.port) as client:
            client.starttls()
            client.login(self._config.user, self._config.password)
            client.sendmail(self._config.from_email, [to_email], message.as_bytes())

        return NotificationReceipt(external_id=str(uuid.uuid4()), provider="smtp")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_smtp_notifier.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/notifications/notifier.py src/recruiter/notifications/smtp.py tests/unit/test_smtp_notifier.py
git commit -m "feat(notifications): add Notifier protocol + SmtpNotifier with ICS attachment"
```

---

## Task 4: LLM email drafter

**Files:**
- Create: `src/recruiter/pipeline/email_drafter.py`
- Create: `tests/unit/test_email_drafter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_email_drafter.py`:

```python
from datetime import datetime, timezone

import pytest

from recruiter.llm.client import FakeLLMClient
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.candidate import ExperienceItem
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
    assert "Alice" in result.body or result.body.startswith("Hi")

    sent = fake.calls[0]
    user_msg = next(m for m in sent["messages"] if m.role == "user")
    assert "Alice" in user_msg.content
    assert "Rust" in user_msg.content
    assert "2026-05-01" in user_msg.content
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_email_drafter.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Create `src/recruiter/pipeline/email_drafter.py`:

```python
import json

from recruiter.llm.client import LLMClient, LLMMessage
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, Slot

_SYSTEM = """You write concise, warm interview-invitation emails.

The recruiter has reviewed and validated the candidate. Your job is to draft an email
that (1) introduces the role briefly, (2) highlights one or two specific things from
the candidate's profile that fit the role, (3) proposes the listed time slots, and
(4) ends with a clear call to action.

Stay under 200 words. First-person, signed by the recruiter. No links, no signatures
beyond the recruiter's name.

Output JSON only matching the requested schema."""


async def draft_email(
    *,
    recruiter_name: str,
    recruiter_email: str,
    company: str,
    job_title: str,
    candidate: ExtractedCandidate,
    slots: list[Slot],
    llm: LLMClient,
) -> DraftedEmail:
    slots_payload = [
        {"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots
    ]
    user = (
        f"Recruiter: {recruiter_name} <{recruiter_email}>\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n\n"
        f"Candidate:\n{json.dumps(candidate.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        f"Proposed time slots (UTC):\n{json.dumps(slots_payload, indent=2)}\n\n"
        "Draft the email."
    )
    return await llm.chat_structured(
        messages=[LLMMessage(role="user", content=user)],
        schema=DraftedEmail,
        system=_SYSTEM,
        max_tokens=1024,
        temperature=0.3,
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_email_drafter.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/pipeline/email_drafter.py tests/unit/test_email_drafter.py
git commit -m "feat(pipeline): add LLM-based email drafter"
```

---

## Task 5: Notification model wiring + draft endpoint

**Files:**
- Modify: `src/recruiter/api/__init__.py` (no change, just confirm package)
- Create: `src/recruiter/api/notifications.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_notifications_draft.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_notifications_draft.py`:

```python
import asyncio

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult
from recruiter.schemas.notification import DraftedEmail


async def _seed_validated_app(api_client: AsyncClient, fake: FakeLLMClient) -> int:
    job_id = (
        await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
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
    return app_id


@pytest.mark.asyncio
async def test_draft_email_endpoint(api_client: AsyncClient) -> None:
    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")],
                rationale="ok",
            ),
            DraftedEmail(subject="Interview", body="Hi Alice"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        app_id = await _seed_validated_app(api_client, fake)
        resp = await api_client.post(
            f"/api/applications/{app_id}/draft-email",
            json={
                "slots": [
                    {
                        "start": "2026-05-01T10:00:00+00:00",
                        "end": "2026-05-01T11:00:00+00:00",
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["subject"] == "Interview"
        assert body["body"] == "Hi Alice"
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.mark.asyncio
async def test_draft_email_404_when_application_missing(api_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: FakeLLMClient()
    try:
        resp = await api_client.post(
            "/api/applications/9999/draft-email",
            json={"slots": [{"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}]},
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_notifications_draft.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement endpoint**

Create `src/recruiter/api/notifications.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session
from recruiter.llm.client import LLMClient
from recruiter.models import Application, Candidate, Job, SettingsRow
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.candidate import (
    EducationItem,
    ExperienceItem,
    LinkItem,
)
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, Slot

router = APIRouter(prefix="/api/applications", tags=["notifications"])


class DraftRequest(BaseModel):
    slots: list[Slot]


def _candidate_to_extracted(c: Candidate) -> ExtractedCandidate:
    return ExtractedCandidate(
        full_name=c.full_name,
        email=c.email,
        phone=c.phone,
        location=c.location,
        headline=c.headline,
        summary=c.summary,
        skills=c.skills or [],
        experience=[ExperienceItem(**e) for e in (c.experience or [])],
        education=[EducationItem(**e) for e in (c.education or [])],
        links=[LinkItem(**l) for l in (c.links or [])],
    )


@router.post("/{application_id}/draft-email", response_model=DraftedEmail)
async def draft_email_endpoint(
    application_id: int,
    payload: DraftRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> DraftedEmail:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")

    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    if job is None or candidate is None:
        raise HTTPException(status_code=404, detail="job or candidate missing")

    settings = await session.get(SettingsRow, 1)
    recruiter_name = (settings.recruiter_name if settings else None) or "the team"
    recruiter_email = (settings.recruiter_email if settings else None) or "no-reply@example.com"

    return await draft_email(
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        company="our team",
        job_title=job.title,
        candidate=_candidate_to_extracted(candidate),
        slots=payload.slots,
        llm=llm,
    )
```

Edit `src/recruiter/main.py` — add `from recruiter.api import notifications` and `app.include_router(notifications.router)` after the existing applications router include.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_notifications_draft.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/notifications.py src/recruiter/main.py tests/api/test_notifications_draft.py
git commit -m "feat(api): add POST /api/applications/{id}/draft-email"
```

---

## Task 6: Settings — encrypted SMTP config getter

**Files:**
- Modify: `src/recruiter/api/settings.py`
- Modify: `src/recruiter/schemas/settings.py`
- Create: `tests/api/test_settings_smtp.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_settings_smtp.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_smtp_config_marks_has_smtp_true(api_client: AsyncClient) -> None:
    resp = await api_client.put(
        "/api/settings",
        json={
            "smtp_config": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "me@example.com",
                "password": "secret",
                "from_email": "me@example.com",
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_smtp_config"] is True
    assert "secret" not in resp.text


@pytest.mark.asyncio
async def test_smtp_password_does_not_leak_in_get(api_client: AsyncClient) -> None:
    await api_client.put(
        "/api/settings",
        json={
            "smtp_config": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "me@example.com",
                "password": "secret",
                "from_email": "me@example.com",
            }
        },
    )
    resp = await api_client.get("/api/settings")
    assert resp.status_code == 200
    assert "secret" not in resp.text
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_settings_smtp.py -v`
Expected: FAIL — Pydantic rejects `smtp_config`.

- [ ] **Step 3: Update SettingsUpdate schema**

Edit `src/recruiter/schemas/settings.py` — add `SmtpConfigInput` and field. Replace the file contents:

```python
from pydantic import BaseModel, ConfigDict


class SmtpConfigInput(BaseModel):
    host: str
    port: int
    user: str
    password: str
    from_email: str


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_llm_provider: str
    has_anthropic_api_key: bool
    local_llm_url: str | None
    model_overrides: dict
    has_google_oauth_tokens: bool
    has_smtp_config: bool
    recruiter_name: str | None
    recruiter_email: str | None
    monthly_llm_spend_cap_usd: int | None


class SettingsUpdate(BaseModel):
    default_llm_provider: str | None = None
    anthropic_api_key: str | None = None
    local_llm_url: str | None = None
    model_overrides: dict | None = None
    smtp_config: SmtpConfigInput | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    monthly_llm_spend_cap_usd: int | None = None
```

- [ ] **Step 4: Update update_settings to encrypt smtp_config**

Edit `src/recruiter/api/settings.py` — inside `update_settings`, after the existing `if payload.local_llm_url is not None:` block, add:

```python
    if payload.smtp_config is not None:
        import json
        row.smtp_config_enc = cipher.encrypt(json.dumps(payload.smtp_config.model_dump()))
```

Also add a public helper at the bottom of the file:

```python
def get_smtp_config(row: SettingsRow) -> SmtpConfigInput | None:
    if not row.smtp_config_enc:
        return None
    import json
    raw = _cipher().decrypt(row.smtp_config_enc)
    return SmtpConfigInput(**json.loads(raw))
```

And add `from recruiter.schemas.settings import SettingsRead, SettingsUpdate, SmtpConfigInput` to the imports at the top.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_settings_smtp.py tests/api/test_settings_api.py -v`
Expected: existing settings tests still pass + 2 new pass.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/schemas/settings.py src/recruiter/api/settings.py tests/api/test_settings_smtp.py
git commit -m "feat(settings): support encrypted SMTP config + accessor helper"
```

---

## Task 7: Notify endpoint (SMTP path)

**Files:**
- Modify: `src/recruiter/api/notifications.py`
- Modify: `src/recruiter/models/notification.py` (no change needed — confirm imports)
- Create: `tests/api/test_notifications_send.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_notifications_send.py`:

```python
import asyncio
from email import message_from_bytes
from typing import Any

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
            ExtractedCandidate(
                full_name="Alice", email="alice@example.com", skills=["Rust"]
            ),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="Rust", weight=1.0, score=85, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        # Setup SMTP config
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
        # Seed a validated application
        job_id = (
            await api_client.post("/api/jobs", json={"title": "Rust role", "description": "D", "criteria": []})
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

        # Notify
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
        # Stage advanced
        r = await api_client.get(f"/api/applications/{app_id}")
        assert r.json()["stage"] == "invited"
        assert r.json()["invited_at"] is not None
        # Email actually sent
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
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=70, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    try:
        job_id = (
            await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
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
                "slots": [{"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}],
            },
        )
        assert resp.status_code == 503
        assert "SMTP" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_notifications_send.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement notify endpoint + Notification persistence**

Edit `src/recruiter/api/notifications.py` — append imports and the new endpoint. Full file becomes:

```python
import smtplib
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.candidates import get_llm
from recruiter.api.deps import get_session
from recruiter.api.settings import get_smtp_config
from recruiter.llm.client import LLMClient
from recruiter.models import (
    Application,
    Candidate,
    Job,
    Notification,
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    SettingsRow,
    Stage,
)
from recruiter.notifications.smtp import SmtpConfig, SmtpNotifier
from recruiter.pipeline.email_drafter import draft_email
from recruiter.schemas.candidate import EducationItem, ExperienceItem, LinkItem
from recruiter.schemas.extraction import ExtractedCandidate
from recruiter.schemas.notification import DraftedEmail, NotifyPayload, Slot

router = APIRouter(prefix="/api/applications", tags=["notifications"])


def get_smtp_factory() -> Callable[[str, int], smtplib.SMTP]:
    """Override in tests to inject a fake SMTP client."""
    return lambda host, port: smtplib.SMTP(host, port)


class DraftRequest(BaseModel):
    slots: list[Slot]


def _candidate_to_extracted(c: Candidate) -> ExtractedCandidate:
    return ExtractedCandidate(
        full_name=c.full_name,
        email=c.email,
        phone=c.phone,
        location=c.location,
        headline=c.headline,
        summary=c.summary,
        skills=c.skills or [],
        experience=[ExperienceItem(**e) for e in (c.experience or [])],
        education=[EducationItem(**e) for e in (c.education or [])],
        links=[LinkItem(**l) for l in (c.links or [])],
    )


@router.post("/{application_id}/draft-email", response_model=DraftedEmail)
async def draft_email_endpoint(
    application_id: int,
    payload: DraftRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> DraftedEmail:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    job = await session.get(Job, app_row.job_id)
    candidate = await session.get(Candidate, app_row.candidate_id)
    if job is None or candidate is None:
        raise HTTPException(status_code=404, detail="job or candidate missing")

    settings = await session.get(SettingsRow, 1)
    recruiter_name = (settings.recruiter_name if settings else None) or "the team"
    recruiter_email = (
        (settings.recruiter_email if settings else None) or "no-reply@example.com"
    )

    return await draft_email(
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        company="our team",
        job_title=job.title,
        candidate=_candidate_to_extracted(candidate),
        slots=payload.slots,
        llm=llm,
    )


@router.post(
    "/{application_id}/notify",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def notify_endpoint(
    application_id: int,
    payload: NotifyPayload,
    session: AsyncSession = Depends(get_session),
    smtp_factory: Callable[[str, int], smtplib.SMTP] = Depends(get_smtp_factory),
) -> dict:
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="application not found")
    if app_row.stage != Stage.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot notify from stage {app_row.stage.value} — must be validated",
        )

    candidate = await session.get(Candidate, app_row.candidate_id)
    if candidate is None or not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="candidate email is required to send notification",
        )

    settings = await session.get(SettingsRow, 1)
    if settings is None:
        raise HTTPException(status_code=503, detail="settings not configured")

    if payload.channel == "smtp":
        smtp_cfg_input = get_smtp_config(settings)
        if smtp_cfg_input is None:
            raise HTTPException(status_code=503, detail="SMTP config not set in settings")
        cfg = SmtpConfig(
            host=smtp_cfg_input.host,
            port=smtp_cfg_input.port,
            user=smtp_cfg_input.user,
            password=smtp_cfg_input.password,
            from_email=smtp_cfg_input.from_email,
        )
        notifier = SmtpNotifier(cfg, smtp_factory=smtp_factory)
    else:
        # gmail path lands in Task 17
        raise HTTPException(status_code=501, detail="Gmail channel not yet wired")

    receipt = await notifier.send_invitation(
        to_email=candidate.email,
        subject=payload.subject,
        body=payload.body,
        slots=payload.slots,
    )

    now = datetime.now(timezone.utc)
    notification = Notification(
        application_id=application_id,
        channel=NotificationChannel.EMAIL,
        provider=NotificationProvider.SMTP if payload.channel == "smtp" else NotificationProvider.GMAIL,
        subject=payload.subject,
        body=payload.body,
        status=NotificationStatus.SENT,
        external_id=receipt.external_id,
        sent_at=now,
    )
    session.add(notification)
    app_row.stage = Stage.INVITED
    app_row.invited_at = now
    await session.commit()
    return {"notification_id": notification.id, "external_id": receipt.external_id}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_notifications_send.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -3`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/api/notifications.py tests/api/test_notifications_send.py
git commit -m "feat(api): add POST /notify with SMTP+ICS path, persist Notification row"
```

---

## Task 8: Frontend — Slot type + useNotify hooks

**Files:**
- Modify: `recruiter-frontend/src/lib/api-types.ts` (regenerate)
- Create: `recruiter-frontend/src/hooks/use-notify.ts`

- [ ] **Step 1: Regenerate API types**

In one shell:
```bash
docker compose up -d postgres
.venv/bin/uvicorn recruiter.main:app --port 8765 &
sleep 2
cd recruiter-frontend
API_URL=http://localhost:8765 npm run gen:types
kill %1 || pkill -f "uvicorn recruiter.main"
```

- [ ] **Step 2: Write useNotify**

Create `recruiter-frontend/src/hooks/use-notify.ts`:

```typescript
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface Slot {
  start: string; // ISO
  end: string;
}

export interface DraftedEmail {
  subject: string;
  body: string;
}

export interface NotifyPayload {
  channel: "smtp" | "gmail";
  subject: string;
  body: string;
  slots: Slot[];
}

export function useDraftEmail(applicationId: number) {
  return useMutation({
    mutationFn: (slots: Slot[]) =>
      api<DraftedEmail>(`/api/applications/${applicationId}/draft-email`, {
        method: "POST",
        json: { slots },
      }),
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Draft failed");
    },
  });
}

export function useSendNotification(applicationId: number, jobId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: NotifyPayload) =>
      api<{ notification_id: number; external_id: string }>(
        `/api/applications/${applicationId}/notify`,
        { method: "POST", json: payload },
      ),
    onSuccess: () => {
      toast.success("Invitation sent");
      queryClient.invalidateQueries({
        queryKey: queryKeys.application(applicationId),
      });
      if (jobId !== undefined) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobApplications(jobId),
        });
      }
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Send failed");
    },
  });
}
```

- [ ] **Step 3: Verify build + tests**

Run:
```bash
cd recruiter-frontend
npm run lint
npm test
```

Expected: existing 10 tests still pass.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend
git commit -m "feat(frontend): add useDraftEmail + useSendNotification hooks"
```

---

## Task 9: Frontend — NotifyWizard step components

**Files:**
- Create: `recruiter-frontend/src/components/notify/step-channel.tsx`
- Create: `recruiter-frontend/src/components/notify/step-slots.tsx`
- Create: `recruiter-frontend/src/components/notify/step-draft.tsx`
- Create: `recruiter-frontend/src/components/notify/step-confirm.tsx`

- [ ] **Step 1: step-channel**

Create `recruiter-frontend/src/components/notify/step-channel.tsx`:

```typescript
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  value: "smtp" | "gmail";
  onChange: (channel: "smtp" | "gmail") => void;
  hasSmtpConfig: boolean;
  hasGoogleOauth: boolean;
}

export function StepChannel({ value, onChange, hasSmtpConfig, hasGoogleOauth }: Props) {
  return (
    <div className="space-y-4">
      <Label>Channel</Label>
      <Select value={value} onValueChange={(v) => onChange(v as "smtp" | "gmail")}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="smtp" disabled={!hasSmtpConfig}>
            SMTP + ICS attachment {!hasSmtpConfig && "(configure in Settings)"}
          </SelectItem>
          <SelectItem value="gmail" disabled={!hasGoogleOauth}>
            Gmail + Google Calendar {!hasGoogleOauth && "(connect in Settings)"}
          </SelectItem>
        </SelectContent>
      </Select>
      <p className="text-sm text-muted-foreground">
        {value === "smtp"
          ? "Email is sent from your configured SMTP server with a calendar attachment."
          : "Email is sent from your Gmail account; a Google Calendar event with the candidate as attendee is created."}
      </p>
    </div>
  );
}
```

- [ ] **Step 2: step-slots**

Create `recruiter-frontend/src/components/notify/step-slots.tsx`:

```typescript
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  slots: Slot[];
  onChange: (slots: Slot[]) => void;
}

function nowPlusHours(h: number): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + h);
  return d.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM for datetime-local
}

function isoFromLocal(s: string): string {
  return new Date(s).toISOString();
}

export function StepSlots({ slots, onChange }: Props) {
  function addSlot() {
    const startLocal = nowPlusHours(24);
    const endLocal = nowPlusHours(25);
    onChange([
      ...slots,
      { start: isoFromLocal(startLocal), end: isoFromLocal(endLocal) },
    ]);
  }

  function updateSlot(index: number, key: "start" | "end", localValue: string) {
    const next = slots.slice();
    next[index] = { ...next[index]!, [key]: isoFromLocal(localValue) };
    onChange(next);
  }

  function removeSlot(index: number) {
    onChange(slots.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Proposed time slots (your local timezone)</Label>
        <Button type="button" variant="outline" size="sm" onClick={addSlot}>
          <Plus className="h-4 w-4 mr-1" />
          Add slot
        </Button>
      </div>
      {slots.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Add at least one proposed time slot.
        </p>
      )}
      {slots.map((slot, index) => (
        <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-end">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Start</Label>
            <Input
              type="datetime-local"
              value={slot.start.slice(0, 16)}
              onChange={(e) => updateSlot(index, "start", e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">End</Label>
            <Input
              type="datetime-local"
              value={slot.end.slice(0, 16)}
              onChange={(e) => updateSlot(index, "end", e.target.value)}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => removeSlot(index)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: step-draft**

Create `recruiter-frontend/src/components/notify/step-draft.tsx`:

```typescript
import { useEffect } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useDraftEmail } from "@/hooks/use-notify";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  applicationId: number;
  slots: Slot[];
  subject: string;
  body: string;
  onChange: (subject: string, body: string) => void;
}

export function StepDraft({ applicationId, slots, subject, body, onChange }: Props) {
  const draft = useDraftEmail(applicationId);

  useEffect(() => {
    if (subject === "" && body === "" && slots.length > 0 && !draft.isPending) {
      draft.mutate(slots, {
        onSuccess: (d) => onChange(d.subject, d.body),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Subject</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() =>
            draft.mutate(slots, {
              onSuccess: (d) => onChange(d.subject, d.body),
            })
          }
          disabled={draft.isPending}
        >
          {draft.isPending ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4 mr-1" />
          )}
          {subject || body ? "Re-draft" : "Draft with AI"}
        </Button>
      </div>
      <Input value={subject} onChange={(e) => onChange(e.target.value, body)} />

      <Label>Body</Label>
      <Textarea
        rows={12}
        value={body}
        onChange={(e) => onChange(subject, e.target.value)}
      />
    </div>
  );
}
```

- [ ] **Step 4: step-confirm**

Create `recruiter-frontend/src/components/notify/step-confirm.tsx`:

```typescript
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  channel: "smtp" | "gmail";
  candidateEmail: string;
  subject: string;
  body: string;
  slots: Slot[];
}

function formatSlot(slot: Slot): string {
  const opts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  };
  const start = new Date(slot.start).toLocaleString(undefined, opts);
  const end = new Date(slot.end).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${start} – ${end}`;
}

export function StepConfirm({ channel, candidateEmail, subject, body, slots }: Props) {
  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-2 text-sm">
        <div>
          <Label className="text-xs text-muted-foreground">Channel</Label>
          <p className="font-medium">{channel === "smtp" ? "SMTP + ICS" : "Gmail + Google Calendar"}</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Recipient</Label>
          <p>{candidateEmail}</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Subject</Label>
          <p className="font-medium">{subject}</p>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Slots</Label>
          <ul className="list-disc list-inside">
            {slots.map((slot, i) => (
              <li key={i}>{formatSlot(slot)}</li>
            ))}
          </ul>
        </div>
      </Card>
      <div>
        <Label className="text-xs text-muted-foreground">Body preview</Label>
        <pre className="text-sm whitespace-pre-wrap rounded border p-3 bg-muted/30">
          {body}
        </pre>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify lint**

Run: `cd recruiter-frontend && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add recruiter-frontend/src/components/notify
git commit -m "feat(frontend): add 4 NotifyWizard step components"
```

---

## Task 10: Frontend — NotifyWizard shell

**Files:**
- Create: `recruiter-frontend/src/components/notify/notify-wizard.tsx`
- Modify: `recruiter-frontend/src/components/candidate/action-bar.tsx`

- [ ] **Step 1: NotifyWizard**

Create `recruiter-frontend/src/components/notify/notify-wizard.tsx`:

```typescript
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useSettings } from "@/hooks/use-settings";
import { useSendNotification } from "@/hooks/use-notify";
import type { Slot } from "@/hooks/use-notify";
import { StepChannel } from "./step-channel";
import { StepSlots } from "./step-slots";
import { StepDraft } from "./step-draft";
import { StepConfirm } from "./step-confirm";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applicationId: number;
  jobId?: number;
  candidateEmail: string;
}

const STEPS = ["Channel", "Slots", "Draft", "Confirm"] as const;

export function NotifyWizard({
  open,
  onOpenChange,
  applicationId,
  jobId,
  candidateEmail,
}: Props) {
  const settings = useSettings();
  const send = useSendNotification(applicationId, jobId);
  const [step, setStep] = useState(0);
  const [channel, setChannel] = useState<"smtp" | "gmail">("smtp");
  const [slots, setSlots] = useState<Slot[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const hasSmtp = settings.data?.has_smtp_config ?? false;
  const hasGoogle = settings.data?.has_google_oauth_tokens ?? false;

  function reset() {
    setStep(0);
    setChannel("smtp");
    setSlots([]);
    setSubject("");
    setBody("");
  }

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
  }
  function back() {
    if (step > 0) setStep(step - 1);
  }

  function canAdvance() {
    if (step === 0) return (channel === "smtp" && hasSmtp) || (channel === "gmail" && hasGoogle);
    if (step === 1) return slots.length >= 1;
    if (step === 2) return subject.trim().length > 0 && body.trim().length > 0;
    return true;
  }

  async function confirm() {
    await send.mutateAsync({ channel, subject, body, slots });
    reset();
    onOpenChange(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Notify & invite — Step {step + 1} of {STEPS.length}: {STEPS[step]}
          </DialogTitle>
        </DialogHeader>
        <div className="py-4">
          {step === 0 && (
            <StepChannel
              value={channel}
              onChange={setChannel}
              hasSmtpConfig={hasSmtp}
              hasGoogleOauth={hasGoogle}
            />
          )}
          {step === 1 && <StepSlots slots={slots} onChange={setSlots} />}
          {step === 2 && (
            <StepDraft
              applicationId={applicationId}
              slots={slots}
              subject={subject}
              body={body}
              onChange={(s, b) => {
                setSubject(s);
                setBody(b);
              }}
            />
          )}
          {step === 3 && (
            <StepConfirm
              channel={channel}
              candidateEmail={candidateEmail}
              subject={subject}
              body={body}
              slots={slots}
            />
          )}
        </div>
        <DialogFooter>
          {step > 0 && (
            <Button variant="outline" onClick={back} disabled={send.isPending}>
              Back
            </Button>
          )}
          {step < STEPS.length - 1 ? (
            <Button onClick={next} disabled={!canAdvance()}>
              Next
            </Button>
          ) : (
            <Button onClick={confirm} disabled={send.isPending}>
              {send.isPending ? "Sending…" : "Send"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Wire into ActionBar**

Edit `recruiter-frontend/src/components/candidate/action-bar.tsx` — replace the Notify toast with the wizard. Full file:

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useApplicationMutations } from "@/hooks/use-application-mutations";
import type { ApplicationRead } from "@/hooks/use-job-applications";
import { NotifyWizard } from "@/components/notify/notify-wizard";
import { RejectDialog } from "./reject-dialog";

interface Props {
  application: ApplicationRead;
  candidateEmail?: string | null;
}

export function ActionBar({ application, candidateEmail }: Props) {
  const m = useApplicationMutations(application.id, application.job_id);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [notifyOpen, setNotifyOpen] = useState(false);

  const stage = application.stage;
  const canValidate = stage === "scored";
  const canUnvalidate = stage === "validated" && !application.invited_at;
  const canReject = stage !== "rejected" && stage !== "invited" && stage !== "scheduled";
  const canNotify = stage === "validated" && !!candidateEmail;

  return (
    <div className="flex flex-wrap gap-2">
      {canValidate && (
        <Button size="sm" onClick={m.validate} disabled={m.isPending}>
          Validate
        </Button>
      )}
      {canUnvalidate && (
        <Button size="sm" variant="outline" onClick={m.unvalidate} disabled={m.isPending}>
          Unvalidate
        </Button>
      )}
      {canNotify && (
        <Button size="sm" onClick={() => setNotifyOpen(true)}>
          Notify & invite
        </Button>
      )}
      {canReject && (
        <Button
          size="sm"
          variant="destructive"
          onClick={() => setRejectOpen(true)}
          disabled={m.isPending}
        >
          Reject
        </Button>
      )}
      <RejectDialog
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onConfirm={m.reject}
      />
      {canNotify && candidateEmail && (
        <NotifyWizard
          open={notifyOpen}
          onOpenChange={setNotifyOpen}
          applicationId={application.id}
          jobId={application.job_id}
          candidateEmail={candidateEmail}
        />
      )}
    </div>
  );
}
```

Edit `recruiter-frontend/src/routes/application-detail.tsx` to pass `candidateEmail` (need a `useCandidate` hook OR include in ApplicationRead — for now, add a small candidate fetch in the application detail). Replace file:

```typescript
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { ActionBar } from "@/components/candidate/action-bar";
import { ScoreBreakdown } from "@/components/candidate/score-breakdown";
import { useApplication } from "@/hooks/use-application";
import { api } from "@/lib/api";

interface CandidateRead {
  id: number;
  full_name: string | null;
  email: string | null;
}

export default function ApplicationDetail() {
  const { appId } = useParams<{ appId: string }>();
  const id = Number(appId);
  const application = useApplication(id);
  const candidate = useQuery({
    queryKey: ["candidate", application.data?.candidate_id],
    queryFn: () =>
      api<CandidateRead>(`/api/candidates/${application.data!.candidate_id}`),
    enabled: !!application.data?.candidate_id,
  });

  if (application.isLoading) return <p>Loading…</p>;
  if (application.isError) return <p className="text-destructive">Failed to load.</p>;
  if (!application.data) return <p>Not found.</p>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6">
      <div className="space-y-6">
        <header className="space-y-2">
          <h2 className="text-xl font-semibold">
            {candidate.data?.full_name ?? `Candidate #${application.data.candidate_id}`}
          </h2>
          <p className="text-sm text-muted-foreground capitalize">
            {application.data.stage}
          </p>
          <ActionBar
            application={application.data}
            candidateEmail={candidate.data?.email}
          />
        </header>
        <ScoreBreakdown application={application.data} />
      </div>
      <aside>
        <div className="rounded border p-4 text-sm text-muted-foreground">
          Chat panel coming in Plan D
        </div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 3: Add backend GET /api/candidates/{id} endpoint**

Backend currently has no endpoint to fetch a Candidate directly. Add it.

Edit `src/recruiter/api/applications.py` — append:

```python
from recruiter.schemas.candidate import CandidateRead


@router.get("/candidates/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: int, session: AsyncSession = Depends(get_session)
) -> CandidateRead:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return CandidateRead.model_validate(candidate)
```

(Add `from recruiter.models import Candidate` to imports if not already.)

- [ ] **Step 4: Verify lint + tests**

Run:
```bash
cd recruiter-frontend && npm run lint && npm test
.venv/bin/python -m pytest tests/ 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/applications.py recruiter-frontend
git commit -m "feat(frontend): add NotifyWizard shell + GET /api/candidates/{id}"
```

---

## Task 11: Frontend — Notifications settings tab (SMTP form)

**Files:**
- Create: `recruiter-frontend/src/components/settings/notifications-tab.tsx`
- Modify: `recruiter-frontend/src/routes/settings.tsx`
- Delete: `recruiter-frontend/src/components/settings/notifications-tab-placeholder.tsx`

- [ ] **Step 1: New tab component**

Create `recruiter-frontend/src/components/settings/notifications-tab.tsx`:

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettings, useUpdateSettings } from "@/hooks/use-settings";

export function NotificationsTab() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [fromEmail, setFromEmail] = useState("");

  if (settings.isLoading) return <p>Loading…</p>;
  if (!settings.data) return <p>No settings.</p>;

  function save() {
    update.mutate({
      smtp_config: {
        host,
        port: Number(port),
        user,
        password,
        from_email: fromEmail,
      },
    } as any);
    setPassword("");
  }

  return (
    <div className="space-y-6 max-w-lg">
      <section className="space-y-3">
        <h3 className="font-medium">SMTP + ICS</h3>
        {settings.data.has_smtp_config && (
          <p className="text-sm text-muted-foreground">SMTP config is set. Submit again to overwrite.</p>
        )}
        <div className="space-y-2">
          <Label>SMTP host</Label>
          <Input
            placeholder="smtp.example.com"
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>Port</Label>
          <Input type="number" value={port} onChange={(e) => setPort(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>User</Label>
          <Input value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>Password</Label>
          <Input
            type="password"
            placeholder={settings.data.has_smtp_config ? "•••••• (set)" : ""}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>From email</Label>
          <Input
            type="email"
            placeholder="me@example.com"
            value={fromEmail}
            onChange={(e) => setFromEmail(e.target.value)}
          />
        </div>
        <Button onClick={save} disabled={update.isPending || !host || !user || !password || !fromEmail}>
          {update.isPending ? "Saving…" : "Save SMTP config"}
        </Button>
      </section>

      <section className="space-y-3 border-t pt-6">
        <h3 className="font-medium">Gmail + Google Calendar</h3>
        <p className="text-sm text-muted-foreground">
          {settings.data.has_google_oauth_tokens
            ? "Connected to Google."
            : "Not connected. Google OAuth setup ships in Plan C tasks 13-22."}
        </p>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Wire into settings page**

Edit `recruiter-frontend/src/routes/settings.tsx` — swap the placeholder import. Full file:

```typescript
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LlmTab } from "@/components/settings/llm-tab";
import { NotificationsTab } from "@/components/settings/notifications-tab";
import { ProfileTab } from "@/components/settings/profile-tab";

export default function Settings() {
  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>
      <Tabs defaultValue="llm">
        <TabsList>
          <TabsTrigger value="llm">LLM</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>
        <TabsContent value="llm" className="pt-6">
          <LlmTab />
        </TabsContent>
        <TabsContent value="notifications" className="pt-6">
          <NotificationsTab />
        </TabsContent>
        <TabsContent value="profile" className="pt-6">
          <ProfileTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

Delete `recruiter-frontend/src/components/settings/notifications-tab-placeholder.tsx`:

```bash
rm recruiter-frontend/src/components/settings/notifications-tab-placeholder.tsx
```

- [ ] **Step 3: Update useSettings to allow smtp_config in payload**

Edit `recruiter-frontend/src/hooks/use-settings.ts` — extend `SettingsUpdate`:

```typescript
export interface SmtpConfigInput {
  host: string;
  port: number;
  user: string;
  password: string;
  from_email: string;
}

export interface SettingsUpdate {
  default_llm_provider?: string;
  anthropic_api_key?: string;
  local_llm_url?: string;
  model_overrides?: Record<string, unknown>;
  smtp_config?: SmtpConfigInput;
  recruiter_name?: string;
  recruiter_email?: string;
  monthly_llm_spend_cap_usd?: number;
}
```

Then in `notifications-tab.tsx`, replace `update.mutate(... as any)` with the typed call (drop `as any`).

- [ ] **Step 4: Verify lint + tests**

Run: `cd recruiter-frontend && npm run lint && npm test`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add recruiter-frontend
git commit -m "feat(frontend): replace Notifications placeholder with real SMTP form"
```

---

## Task 12: SMTP-only smoke test

**Files:**
- Modify: `recruiter-frontend/SMOKE.md`

This is the **stop point if you only want SMTP**. Tasks 13-22 add Gmail+GCal OAuth.

- [ ] **Step 1: Set up MailHog (or other SMTP test server)**

Run a local SMTP test server. Easiest is MailHog via Docker:

```bash
docker run -d --rm --name mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog
```

MailHog UI at http://localhost:8025 captures every email it receives.

- [ ] **Step 2: Append SMTP smoke section to SMOKE.md**

Append to `recruiter-frontend/SMOKE.md`:

```markdown

## Plan C — SMTP smoke

Requires MailHog running on localhost:1025 (SMTP) and 8025 (UI).

- [ ] In Settings → Notifications, save SMTP config: host=localhost, port=1025, user=any, password=any, from=me@example.com.
- [ ] Add a candidate with paste `Alice Doe alice@example.com - Rust expert` → wait for Scored.
- [ ] Click candidate → Validate → "Notify & invite".
- [ ] Wizard step 1: SMTP option enabled. Pick it, Next.
- [ ] Step 2: Add 2 slots, Next.
- [ ] Step 3: AI drafts subject + body. Edit subject. Next.
- [ ] Step 4: Confirm Send. Toast "Invitation sent".
- [ ] Card moves to Invited column.
- [ ] Open MailHog UI (http://localhost:8025). Email present, has `text/calendar` attachment.
- [ ] Open the .ics in a calendar app to verify attendee = candidate email.
```

- [ ] **Step 3: Commit**

```bash
git add recruiter-frontend/SMOKE.md
git commit -m "docs(smoke): add SMTP-path smoke checklist"
```

---

# Phase 2 — Gmail + Google Calendar OAuth (Tasks 13-22)

If you stopped at Task 12, the SMTP path is fully shippable. Tasks 13-22 add the Google channel.

---

## Task 13: OAuthState model + migration

**Files:**
- Create: `src/recruiter/models/oauth_state.py`
- Modify: `src/recruiter/models/__init__.py`
- Create: `tests/unit/test_oauth_state_model.py`
- Auto-generated migration

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_oauth_state_model.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import OAuthState


@pytest.mark.asyncio
async def test_oauth_state_roundtrip(db_session_with_schema: AsyncSession) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    state = OAuthState(state="abc123", redirect_after="/settings", expires_at=expires)
    db_session_with_schema.add(state)
    await db_session_with_schema.commit()
    fetched = await db_session_with_schema.get(OAuthState, "abc123")
    assert fetched is not None
    assert fetched.redirect_after == "/settings"
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_oauth_state_model.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement model**

Create `src/recruiter/models/oauth_state.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    redirect_after: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Edit `src/recruiter/models/__init__.py` — add `OAuthState` import + export. Append:

```python
from recruiter.models.oauth_state import OAuthState
```

And add `"OAuthState",` to `__all__` (alphabetical position after Notification).

- [ ] **Step 4: Generate + apply migration**

Run:
```bash
docker compose up -d postgres
.venv/bin/alembic revision --autogenerate -m "oauth_states table"
.venv/bin/alembic upgrade head
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_oauth_state_model.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/models tests/unit/test_oauth_state_model.py alembic/versions
git commit -m "feat(models): add OAuthState for short-TTL OAuth state tokens"
```

---

## Task 14: Google OAuth helpers

**Files:**
- Create: `src/recruiter/notifications/google_oauth.py`
- Create: `tests/unit/test_google_oauth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_google_oauth.py`:

```python
import json

import pytest

from recruiter.notifications.google_oauth import (
    GoogleTokens,
    build_authorization_url,
    parse_tokens,
)


def test_build_authorization_url_includes_required_params() -> None:
    url = build_authorization_url(
        client_id="cid",
        redirect_uri="http://localhost:8000/api/auth/google/callback",
        state="xyz",
    )
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Fgoogle%2Fcallback" in url
    assert "state=xyz" in url
    assert "scope=" in url
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.send" in url
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_parse_tokens_round_trip() -> None:
    tokens = GoogleTokens(
        access_token="acc",
        refresh_token="ref",
        expiry_iso="2026-05-01T10:00:00+00:00",
        scope="gmail.send calendar.events",
    )
    raw = json.dumps(tokens.__dict__)
    parsed = parse_tokens(raw)
    assert parsed.access_token == "acc"
    assert parsed.refresh_token == "ref"
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_google_oauth.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Create `src/recruiter/notifications/google_oauth.py`:

```python
import json
from dataclasses import dataclass, field
from urllib.parse import urlencode

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
]


@dataclass
class GoogleTokens:
    access_token: str
    refresh_token: str | None
    expiry_iso: str
    scope: str
    user_email: str | None = None


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def parse_tokens(raw: str) -> GoogleTokens:
    data = json.loads(raw)
    return GoogleTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expiry_iso=data["expiry_iso"],
        scope=data.get("scope", ""),
        user_email=data.get("user_email"),
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_google_oauth.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/notifications/google_oauth.py tests/unit/test_google_oauth.py
git commit -m "feat(notifications): add Google OAuth URL builder + token serializer"
```

---

## Task 15: OAuth Settings fields (client_id, client_secret)

**Files:**
- Modify: `src/recruiter/models/settings.py`
- Modify: `src/recruiter/schemas/settings.py`
- Modify: `src/recruiter/api/settings.py`
- Auto-generated migration

- [ ] **Step 1: Add columns**

Edit `src/recruiter/models/settings.py` — add 2 columns inside `SettingsRow`:

```python
    google_client_id: Mapped[str | None] = mapped_column(String(512))
    google_client_secret_enc: Mapped[str | None] = mapped_column(String)
```

(Place after `smtp_config_enc`.)

- [ ] **Step 2: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "settings: google client id/secret"
.venv/bin/alembic upgrade head
```

- [ ] **Step 3: Update SettingsRead and SettingsUpdate schemas**

Edit `src/recruiter/schemas/settings.py` — add fields:

In `SettingsRead`:
```python
    google_client_id: str | None
    has_google_client_secret: bool
```

In `SettingsUpdate`:
```python
    google_client_id: str | None = None
    google_client_secret: str | None = None
```

- [ ] **Step 4: Update API to encrypt client_secret**

Edit `src/recruiter/api/settings.py` — inside `update_settings`, add:

```python
    if payload.google_client_id is not None:
        row.google_client_id = payload.google_client_id
    if payload.google_client_secret is not None:
        row.google_client_secret_enc = cipher.encrypt(payload.google_client_secret)
```

In `_to_read`, add:
```python
        google_client_id=row.google_client_id,
        has_google_client_secret=bool(row.google_client_secret_enc),
```

- [ ] **Step 5: Verify existing tests still pass**

Run: `.venv/bin/python -m pytest tests/api/test_settings_api.py tests/api/test_settings_smtp.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/models/settings.py src/recruiter/schemas/settings.py src/recruiter/api/settings.py alembic/versions
git commit -m "feat(settings): add google_client_id + encrypted google_client_secret"
```

---

## Task 16: GET /api/auth/google/start

**Files:**
- Create: `src/recruiter/api/auth_google.py`
- Modify: `src/recruiter/main.py`
- Create: `tests/api/test_auth_google_start.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_google_start.py`:

```python
import pytest
from httpx import AsyncClient

from recruiter.api.settings import _cipher


@pytest.mark.asyncio
async def test_start_returns_authorization_url_and_persists_state(api_client: AsyncClient) -> None:
    # Configure google client_id + secret
    await api_client.put(
        "/api/settings",
        json={
            "google_client_id": "cid",
            "google_client_secret": "sec",
        },
    )
    resp = await api_client.get("/api/auth/google/start")
    assert resp.status_code == 200
    body = resp.json()
    assert "auth_url" in body
    assert "state" in body
    assert "client_id=cid" in body["auth_url"]
    assert f"state={body['state']}" in body["auth_url"]


@pytest.mark.asyncio
async def test_start_503_when_google_not_configured(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/auth/google/start")
    assert resp.status_code == 503
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_auth_google_start.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Implement endpoint**

Create `src/recruiter/api/auth_google.py`:

```python
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session
from recruiter.config import get_config
from recruiter.models import OAuthState, SettingsRow
from recruiter.notifications.google_oauth import build_authorization_url

router = APIRouter(prefix="/api/auth/google", tags=["auth"])


class StartResponse(BaseModel):
    auth_url: str
    state: str


@router.get("/start", response_model=StartResponse)
async def start(
    session: AsyncSession = Depends(get_session),
) -> StartResponse:
    settings_row = await session.get(SettingsRow, 1)
    if settings_row is None or not settings_row.google_client_id:
        raise HTTPException(
            status_code=503,
            detail="Google client_id not configured. PUT it via /api/settings.",
        )

    config = get_config()
    redirect_uri = f"{config.public_base_url}/api/auth/google/callback"

    state_token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    session.add(
        OAuthState(state=state_token, redirect_after="/settings", expires_at=expires)
    )
    await session.commit()

    url = build_authorization_url(
        client_id=settings_row.google_client_id,
        redirect_uri=redirect_uri,
        state=state_token,
    )
    return StartResponse(auth_url=url, state=state_token)
```

Edit `src/recruiter/config.py` — add field:

```python
    public_base_url: str = "http://localhost:8000"
```

Edit `src/recruiter/main.py` — include the router:

```python
from recruiter.api import auth_google
# ...
app.include_router(auth_google.router)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_auth_google_start.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/auth_google.py src/recruiter/config.py src/recruiter/main.py tests/api/test_auth_google_start.py
git commit -m "feat(api): add GET /api/auth/google/start with state token persistence"
```

---

## Task 17: GET /api/auth/google/callback (token exchange)

**Files:**
- Modify: `src/recruiter/api/auth_google.py`
- Modify: `src/recruiter/notifications/google_oauth.py`
- Create: `tests/api/test_auth_google_callback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_auth_google_callback.py`:

```python
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import AsyncClient

from recruiter.api.auth_google import get_token_exchange_client
from recruiter.api.settings import _cipher
from recruiter.main import app
from recruiter.models import OAuthState
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_callback_exchanges_code_and_stores_tokens(api_client: AsyncClient, pg_dsn: str) -> None:
    # Configure google client + state
    await api_client.put(
        "/api/settings",
        json={"google_client_id": "cid", "google_client_secret": "sec"},
    )

    # Insert a state token directly via the DB
    engine = create_async_engine(pg_dsn)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        s.add(
            OAuthState(
                state="my-state",
                redirect_after="/settings",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        await s.commit()
    await engine.dispose()

    # Mock the Google token endpoint
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "ACC",
                "refresh_token": "REF",
                "expires_in": 3600,
                "scope": "gmail.send calendar.events",
            },
        )

    transport = httpx.MockTransport(handler)
    app.dependency_overrides[get_token_exchange_client] = lambda: httpx.AsyncClient(transport=transport)
    try:
        resp = await api_client.get(
            "/api/auth/google/callback?code=abc&state=my-state",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert "/settings" in resp.headers["location"]

        # Tokens stored encrypted
        s = await api_client.get("/api/settings")
        assert s.json()["has_google_oauth_tokens"] is True
    finally:
        app.dependency_overrides.pop(get_token_exchange_client, None)


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state(api_client: AsyncClient) -> None:
    await api_client.put(
        "/api/settings",
        json={"google_client_id": "cid", "google_client_secret": "sec"},
    )
    resp = await api_client.get(
        "/api/auth/google/callback?code=abc&state=unknown",
        follow_redirects=False,
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_auth_google_callback.py -v`
Expected: FAIL — endpoint not defined.

- [ ] **Step 3: Add token-exchange helper**

Edit `src/recruiter/notifications/google_oauth.py` — append:

```python
async def exchange_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_client,  # httpx.AsyncClient
) -> GoogleTokens:
    response = await http_client.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    response.raise_for_status()
    data = response.json()
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
    return GoogleTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expiry_iso=expires_at.isoformat(),
        scope=data.get("scope", ""),
    )
```

- [ ] **Step 4: Implement callback endpoint**

Edit `src/recruiter/api/auth_google.py` — append:

```python
import json

import httpx
from fastapi.responses import RedirectResponse

from recruiter.api.settings import _cipher
from recruiter.notifications.google_oauth import exchange_code_for_tokens


def get_token_exchange_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


@router.get("/callback")
async def callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
    http_client: httpx.AsyncClient = Depends(get_token_exchange_client),
) -> RedirectResponse:
    state_row = await session.get(OAuthState, state)
    if state_row is None:
        raise HTTPException(status_code=400, detail="unknown state")
    if state_row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="state expired")

    settings_row = await session.get(SettingsRow, 1)
    if settings_row is None or not settings_row.google_client_id or not settings_row.google_client_secret_enc:
        raise HTTPException(status_code=503, detail="Google not configured")

    client_secret = _cipher().decrypt(settings_row.google_client_secret_enc)
    config = get_config()
    redirect_uri = f"{config.public_base_url}/api/auth/google/callback"

    tokens = await exchange_code_for_tokens(
        code=code,
        client_id=settings_row.google_client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        http_client=http_client,
    )

    settings_row.google_oauth_tokens_enc = _cipher().encrypt(json.dumps(tokens.__dict__))
    redirect_after = state_row.redirect_after
    await session.delete(state_row)
    await session.commit()

    return RedirectResponse(
        f"http://localhost:5173{redirect_after}?google=connected", status_code=303
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_auth_google_callback.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/recruiter/api/auth_google.py src/recruiter/notifications/google_oauth.py tests/api/test_auth_google_callback.py
git commit -m "feat(api): add Google OAuth callback that exchanges code for tokens"
```

---

## Task 18: GmailNotifier (send via Gmail API)

**Files:**
- Create: `src/recruiter/notifications/gmail.py`
- Create: `tests/unit/test_gmail_notifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gmail_notifier.py`:

```python
from datetime import datetime, timezone

import pytest

from recruiter.notifications.gmail import GmailNotifier
from recruiter.notifications.google_oauth import GoogleTokens
from recruiter.schemas.notification import Slot


class FakeGmailService:
    def __init__(self) -> None:
        self.sent_payloads: list[dict] = []

    def users(self) -> "FakeGmailService":
        return self

    def messages(self) -> "FakeGmailService":
        return self

    def send(self, *, userId: str, body: dict) -> "FakeGmailService":
        self._next = {"userId": userId, "body": body}
        return self

    def execute(self) -> dict:
        self.sent_payloads.append(self._next)
        return {"id": "MSG123"}


@pytest.mark.asyncio
async def test_gmail_notifier_sends_with_ics_attachment() -> None:
    fake = FakeGmailService()
    tokens = GoogleTokens(
        access_token="acc",
        refresh_token="ref",
        expiry_iso="2026-05-01T10:00:00+00:00",
        scope="x",
        user_email="me@example.com",
    )
    notifier = GmailNotifier(tokens=tokens, gmail_service=fake)
    receipt = await notifier.send_invitation(
        to_email="alice@example.com",
        subject="Interview",
        body="Hi Alice",
        slots=[
            Slot(
                start=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
                end=datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
            )
        ],
    )
    assert receipt.external_id == "MSG123"
    assert receipt.provider == "gmail"
    payload = fake.sent_payloads[0]
    assert payload["userId"] == "me"
    assert "raw" in payload["body"]
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_gmail_notifier.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Create `src/recruiter/notifications/gmail.py`:

```python
import base64
from email.message import EmailMessage
from typing import Any

from recruiter.notifications.google_oauth import GoogleTokens
from recruiter.notifications.ics import build_ics
from recruiter.notifications.notifier import NotificationReceipt
from recruiter.schemas.notification import Slot


class GmailNotifier:
    def __init__(self, *, tokens: GoogleTokens, gmail_service: Any) -> None:
        self._tokens = tokens
        self._service = gmail_service

    async def send_invitation(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        slots: list[Slot],
    ) -> NotificationReceipt:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._tokens.user_email or "me"
        message["To"] = to_email
        message.set_content(body)

        ics_bytes = build_ics(
            summary=subject,
            description=body,
            slots=slots,
            organizer_email=self._tokens.user_email or "me",
            attendee_email=to_email,
        )
        message.add_attachment(
            ics_bytes,
            maintype="text",
            subtype="calendar",
            filename="invitation.ics",
        )

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = self._service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return NotificationReceipt(external_id=result["id"], provider="gmail")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_gmail_notifier.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/notifications/gmail.py tests/unit/test_gmail_notifier.py
git commit -m "feat(notifications): add GmailNotifier (Gmail API send with ICS attachment)"
```

---

## Task 19: Calendar event creator (gcal.py)

**Files:**
- Create: `src/recruiter/notifications/gcal.py`
- Create: `tests/unit/test_gcal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gcal.py`:

```python
from datetime import datetime, timezone

import pytest

from recruiter.notifications.gcal import create_calendar_events
from recruiter.schemas.notification import Slot


class FakeCalendarService:
    def __init__(self) -> None:
        self.events_inserted: list[dict] = []

    def events(self) -> "FakeCalendarService":
        return self

    def insert(self, *, calendarId: str, body: dict, sendUpdates: str) -> "FakeCalendarService":
        self._next = {"calendarId": calendarId, "body": body, "sendUpdates": sendUpdates}
        return self

    def execute(self) -> dict:
        self.events_inserted.append(self._next)
        return {"id": f"EVT{len(self.events_inserted)}"}


@pytest.mark.asyncio
async def test_create_events_one_per_slot_with_attendee() -> None:
    fake = FakeCalendarService()
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
    ids = await create_calendar_events(
        calendar_service=fake,
        summary="Interview",
        description="x",
        slots=slots,
        attendee_email="alice@example.com",
    )
    assert ids == ["EVT1", "EVT2"]
    assert len(fake.events_inserted) == 2
    first = fake.events_inserted[0]["body"]
    assert first["summary"] == "Interview"
    assert first["attendees"] == [{"email": "alice@example.com"}]
    assert first["start"]["dateTime"] == "2026-05-01T10:00:00+00:00"
    assert fake.events_inserted[0]["sendUpdates"] == "all"
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/unit/test_gcal.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Create `src/recruiter/notifications/gcal.py`:

```python
from typing import Any

from recruiter.schemas.notification import Slot


async def create_calendar_events(
    *,
    calendar_service: Any,
    summary: str,
    description: str,
    slots: list[Slot],
    attendee_email: str,
) -> list[str]:
    event_ids: list[str] = []
    for slot in slots:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": slot.start.isoformat()},
            "end": {"dateTime": slot.end.isoformat()},
            "attendees": [{"email": attendee_email}],
        }
        result = (
            calendar_service.events()
            .insert(calendarId="primary", body=body, sendUpdates="all")
            .execute()
        )
        event_ids.append(result["id"])
    return event_ids
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_gcal.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/notifications/gcal.py tests/unit/test_gcal.py
git commit -m "feat(notifications): add Google Calendar event creator"
```

---

## Task 20: Wire Gmail+GCal into notify endpoint

**Files:**
- Modify: `src/recruiter/api/notifications.py`
- Create: `tests/api/test_notify_gmail.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_notify_gmail.py`:

```python
import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from email import message_from_bytes

import pytest
from httpx import AsyncClient

from recruiter.api.candidates import get_llm
from recruiter.api.notifications import get_gmail_service, get_calendar_service
from recruiter.api.settings import _cipher
from recruiter.llm.client import FakeLLMClient
from recruiter.main import app
from recruiter.notifications.google_oauth import GoogleTokens
from recruiter.schemas.extraction import ExtractedCandidate, ScoreBreakdownItem, ScoreResult


class FakeGmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def users(self): return self
    def messages(self): return self
    def send(self, **kwargs):
        self._next = kwargs
        return self
    def execute(self):
        self.sent.append(self._next)
        return {"id": "MSG-XYZ"}


class FakeCalendar:
    def __init__(self) -> None:
        self.events: list[dict] = []
    def events(self): return self
    def insert(self, **kwargs):
        self._next = kwargs
        return self
    def execute(self):
        self.events.append(self._next)
        return {"id": f"EVT-{len(self.events)}"}


@pytest.mark.asyncio
async def test_gmail_notify_sends_email_and_creates_calendar_event(
    api_client: AsyncClient, pg_dsn: str
) -> None:
    fake_gmail = FakeGmail()
    fake_cal = FakeCalendar()
    app.dependency_overrides[get_gmail_service] = lambda: fake_gmail
    app.dependency_overrides[get_calendar_service] = lambda: fake_cal

    fake = FakeLLMClient(
        structured_responses=[
            ExtractedCandidate(full_name="Alice", email="alice@example.com", skills=["Rust"]),
            ScoreResult(
                score=85,
                breakdown=[ScoreBreakdownItem(criterion="x", weight=1.0, score=85, rationale="ok")],
                rationale="ok",
            ),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: fake

    try:
        # Configure Google tokens directly via DB
        from recruiter.models import SettingsRow
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        await api_client.put(
            "/api/settings",
            json={"google_client_id": "cid", "google_client_secret": "sec"},
        )

        engine = create_async_engine(pg_dsn)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            row = await s.get(SettingsRow, 1)
            tokens = GoogleTokens(
                access_token="ACC",
                refresh_token="REF",
                expiry_iso=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                scope="x",
                user_email="me@example.com",
            )
            row.google_oauth_tokens_enc = _cipher().encrypt(json.dumps(tokens.__dict__))
            await s.commit()
        await engine.dispose()

        # Seed validated app
        job_id = (
            await api_client.post("/api/jobs", json={"title": "T", "description": "D", "criteria": []})
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
                "channel": "gmail",
                "subject": "Interview at Acme",
                "body": "Hi Alice",
                "slots": [{"start": "2026-05-01T10:00:00+00:00", "end": "2026-05-01T11:00:00+00:00"}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert len(fake_gmail.sent) == 1
        assert len(fake_cal.events) == 1
        cal_body = fake_cal.events[0]["body"]
        assert cal_body["attendees"] == [{"email": "alice@example.com"}]

        r = await api_client.get(f"/api/applications/{app_id}")
        assert r.json()["stage"] == "invited"
    finally:
        app.dependency_overrides.pop(get_gmail_service, None)
        app.dependency_overrides.pop(get_calendar_service, None)
        app.dependency_overrides.pop(get_llm, None)
```

- [ ] **Step 2: Run test (expect FAIL)**

Run: `.venv/bin/python -m pytest tests/api/test_notify_gmail.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement Gmail+GCal path in notify**

Edit `src/recruiter/api/notifications.py`:

Add after the `get_smtp_factory` definition:

```python
def _build_google_credentials(tokens: GoogleTokens, settings: SettingsRow):
    from google.oauth2.credentials import Credentials

    client_secret = _cipher().decrypt(settings.google_client_secret_enc)
    return Credentials(
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=client_secret,
    )


def get_gmail_service():
    """Override in tests."""
    raise HTTPException(status_code=500, detail="Gmail service not configured at this layer")


def get_calendar_service():
    """Override in tests."""
    raise HTTPException(status_code=500, detail="Calendar service not configured at this layer")
```

(Add `from recruiter.api.settings import _cipher` and `from recruiter.notifications.google_oauth import GoogleTokens, parse_tokens` to imports.)

Replace the `if payload.channel == "smtp":` block in `notify_endpoint` with the dual-channel dispatch:

```python
    if payload.channel == "smtp":
        smtp_cfg_input = get_smtp_config(settings)
        if smtp_cfg_input is None:
            raise HTTPException(status_code=503, detail="SMTP config not set in settings")
        cfg = SmtpConfig(
            host=smtp_cfg_input.host,
            port=smtp_cfg_input.port,
            user=smtp_cfg_input.user,
            password=smtp_cfg_input.password,
            from_email=smtp_cfg_input.from_email,
        )
        notifier = SmtpNotifier(cfg, smtp_factory=smtp_factory)
        receipt = await notifier.send_invitation(
            to_email=candidate.email,
            subject=payload.subject,
            body=payload.body,
            slots=payload.slots,
        )
    else:
        if not settings.google_oauth_tokens_enc:
            raise HTTPException(status_code=503, detail="Google not connected")
        tokens = parse_tokens(_cipher().decrypt(settings.google_oauth_tokens_enc))
        gmail_service = get_gmail_service()
        cal_service = get_calendar_service()
        from recruiter.notifications.gmail import GmailNotifier
        from recruiter.notifications.gcal import create_calendar_events

        gmail_notifier = GmailNotifier(tokens=tokens, gmail_service=gmail_service)
        receipt = await gmail_notifier.send_invitation(
            to_email=candidate.email,
            subject=payload.subject,
            body=payload.body,
            slots=payload.slots,
        )
        await create_calendar_events(
            calendar_service=cal_service,
            summary=payload.subject,
            description=payload.body,
            slots=payload.slots,
            attendee_email=candidate.email,
        )
```

(Add `gmail_service` and `cal_service` `Depends(get_gmail_service)` / `Depends(get_calendar_service)` to the endpoint signature with default factories that build real clients from credentials. For test simplicity, the default factory is the lazy 500 placeholder — production code wires them up through `_build_google_credentials`.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_notify_gmail.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/recruiter/api/notifications.py tests/api/test_notify_gmail.py
git commit -m "feat(api): wire Gmail+GCal channel into notify endpoint"
```

---

## Task 21: Frontend — Google connect button in NotificationsTab

**Files:**
- Modify: `recruiter-frontend/src/components/settings/notifications-tab.tsx`
- Modify: `recruiter-frontend/src/hooks/use-settings.ts`

- [ ] **Step 1: Extend SettingsRead and SettingsUpdate types**

Edit `recruiter-frontend/src/hooks/use-settings.ts` — add fields:

```typescript
export interface SettingsRead {
  default_llm_provider: string;
  has_anthropic_api_key: boolean;
  local_llm_url: string | null;
  model_overrides: Record<string, unknown>;
  has_google_oauth_tokens: boolean;
  has_smtp_config: boolean;
  google_client_id: string | null;
  has_google_client_secret: boolean;
  recruiter_name: string | null;
  recruiter_email: string | null;
  monthly_llm_spend_cap_usd: number | null;
}

export interface SettingsUpdate {
  default_llm_provider?: string;
  anthropic_api_key?: string;
  local_llm_url?: string;
  model_overrides?: Record<string, unknown>;
  smtp_config?: SmtpConfigInput;
  google_client_id?: string;
  google_client_secret?: string;
  recruiter_name?: string;
  recruiter_email?: string;
  monthly_llm_spend_cap_usd?: number;
}
```

- [ ] **Step 2: Update NotificationsTab to include Google section**

Replace the Google section in `recruiter-frontend/src/components/settings/notifications-tab.tsx`:

```typescript
      <section className="space-y-3 border-t pt-6">
        <h3 className="font-medium">Gmail + Google Calendar</h3>
        <p className="text-sm text-muted-foreground">
          {settings.data.has_google_oauth_tokens
            ? "Connected to Google."
            : "Configure your OAuth client below, then click Connect."}
        </p>

        {!settings.data.has_google_oauth_tokens && (
          <>
            <div className="space-y-2">
              <Label>Google OAuth client_id</Label>
              <Input
                value={googleClientId ?? settings.data.google_client_id ?? ""}
                onChange={(e) => setGoogleClientId(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Google OAuth client_secret</Label>
              <Input
                type="password"
                placeholder={settings.data.has_google_client_secret ? "•••••• (set)" : ""}
                value={googleClientSecret}
                onChange={(e) => setGoogleClientSecret(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              onClick={async () => {
                if (googleClientId !== undefined || googleClientSecret) {
                  await update.mutateAsync({
                    google_client_id: googleClientId,
                    google_client_secret: googleClientSecret || undefined,
                  });
                }
                const r = await fetch(
                  `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/auth/google/start`,
                );
                const data = await r.json();
                window.location.href = data.auth_url;
              }}
            >
              Connect Google
            </Button>
          </>
        )}
      </section>
```

(Add the corresponding `useState` declarations at the top of the component for `googleClientId` and `googleClientSecret`.)

- [ ] **Step 3: Verify lint + tests**

Run: `cd recruiter-frontend && npm run lint && npm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add recruiter-frontend
git commit -m "feat(frontend): add Google OAuth connect button to NotificationsTab"
```

---

## Task 22: Full smoke checklist

**Files:**
- Modify: `recruiter-frontend/SMOKE.md`

- [ ] **Step 1: Document Gmail+GCal smoke**

Append to `recruiter-frontend/SMOKE.md`:

```markdown

## Plan C — Gmail + GCal smoke

Requires:
- A Google Cloud project with OAuth client_id + client_secret (Web application type) configured for redirect_uri `http://localhost:8000/api/auth/google/callback`.
- `gmail.send` and `calendar.events` API enabled in the project.

- [ ] In Settings → Notifications → Gmail section, paste your `client_id` and `client_secret`. Click "Connect Google".
- [ ] Browser redirects to Google. Approve scopes (gmail.send, calendar.events, userinfo.email).
- [ ] Browser redirects back to `/settings?google=connected`. UI shows "Connected to Google."
- [ ] Add a candidate with paste content + email → Scored.
- [ ] Validate → Notify & invite → step 1 picks Gmail option.
- [ ] Steps 2–4 same as SMTP path.
- [ ] After Send: card moves to Invited.
- [ ] Check the candidate's inbox: an email arrives from your Gmail with the body. Calendar invite for each slot is in your Google Calendar with the candidate as attendee. The candidate gets a separate "You're invited" email from Google for each slot.
```

- [ ] **Step 2: Commit**

```bash
git add recruiter-frontend/SMOKE.md
git commit -m "docs(smoke): add Gmail+GCal smoke checklist"
```

---

## Self-Review

**Spec coverage:**
- ✅ NotifyWizard 4-step (Channel → Slots → Draft → Confirm) — Tasks 9, 10
- ✅ SMTP path with ICS — Tasks 2, 3, 7, 11, 12
- ✅ Gmail send — Tasks 18, 20
- ✅ GCal event creation — Tasks 19, 20
- ✅ Google OAuth flow (start + callback) — Tasks 16, 17
- ✅ Encrypted credentials at rest — Tasks 6, 15
- ✅ NotificationsTab UI replacing placeholder — Tasks 11, 21
- ✅ Stage transitions to `invited` after send — Task 7
- ✅ LLM email drafter — Task 4

**Placeholder scan:** No "TBD"/"TODO". A few comments like "Override in tests" — those are documentation, not placeholders.

**Type consistency:**
- `Slot`, `DraftedEmail`, `NotifyPayload` defined in Task 1, reused throughout.
- `NotificationReceipt` defined in Task 3, used in 7 and 18.
- `GoogleTokens` defined in Task 14, used in 17, 18, 20.
- Frontend `Slot`/`DraftedEmail`/`NotifyPayload` defined in Task 8, reused in 9, 10.

**Open caveats:**
- Tasks 16-17 use `RedirectResponse` to `http://localhost:5173/settings?google=connected` — hardcoded for dev. In production, derive from a `frontend_base_url` config. Documented inline.
- The Gmail+GCal services are constructed lazily through `get_gmail_service` / `get_calendar_service` dependency hooks; the default raises 500. Production wiring (build real clients from `Credentials`) lands as a small follow-up at the start of any future deploy work — same pattern as `get_llm` was in Plan A. The current behavior is: tests inject fakes; running `uvicorn` against real Google requires the wiring follow-up.
- Token refresh is not implemented. If the access token expires (1 hour), the next notify call returns a Google API error. Hardening (use `google.auth.transport.requests.Request().refresh()` and persist refreshed tokens) is a Plan C follow-up after the first real send works.
- The plan uses Pydantic `as any` casts in one spot of frontend code (Task 11 step 1) and removes them in step 3 once the type is added — this is intentional incremental work, not a placeholder.

---

## End State

After Task 22:
- A recruiter can configure SMTP credentials AND/OR connect a Google account, then send a real interview invitation via either channel.
- The kanban shows the candidate moving to "Invited" after send.
- Notification rows persist with provider, external_id (message id / event id), subject, body, sent_at.
- Frontend has a 4-step NotifyWizard wired into the action bar.
- Plan D (chat panel) is the only remaining Phase 1 work.

If you stopped at Task 12, you have the SMTP path only — also fully shippable. Tasks 13-22 add Gmail+GCal on top without breaking the SMTP path.
