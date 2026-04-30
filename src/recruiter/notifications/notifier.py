from dataclasses import dataclass
from typing import Protocol

from recruiter.schemas.notification import Slot


@dataclass
class NotificationReceipt:
    external_id: str
    provider: str  # "smtp" | "gmail"


class Notifier(Protocol):
    async def send_invitation(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        slots: list[Slot],
    ) -> NotificationReceipt: ...
