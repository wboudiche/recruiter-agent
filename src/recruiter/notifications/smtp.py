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
    use_starttls: bool = True


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
            if self._config.use_starttls:
                client.starttls()
            if self._config.user and self._config.password:
                client.login(self._config.user, self._config.password)
            client.sendmail(self._config.from_email, [to_email], message.as_bytes())

        return NotificationReceipt(external_id=str(uuid.uuid4()), provider="smtp")
