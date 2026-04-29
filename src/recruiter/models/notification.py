from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class NotificationChannel(str, Enum):
    EMAIL = "email"
    CALENDAR = "calendar"


class NotificationProvider(str, Enum):
    GMAIL = "gmail"
    SMTP = "smtp"


class NotificationStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel", values_callable=lambda x: [e.value for e in x])
    )
    provider: Mapped[NotificationProvider] = mapped_column(
        SAEnum(NotificationProvider, name="notification_provider", values_callable=lambda x: [e.value for e in x])
    )
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(String)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", values_callable=lambda x: [e.value for e in x])
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
