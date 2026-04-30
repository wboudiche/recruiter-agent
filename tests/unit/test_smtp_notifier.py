from datetime import datetime, timezone
from email import message_from_bytes

import pytest

from recruiter.notifications.smtp import SmtpConfig, SmtpNotifier
from recruiter.schemas.notification import Slot


class FakeSmtp:
    def __init__(self) -> None:
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
    types = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in types
    assert "text/calendar" in types
