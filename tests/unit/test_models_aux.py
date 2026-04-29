import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.models import (
    EventLog,
    Notification,
    NotificationChannel,
    NotificationProvider,
    NotificationStatus,
    SettingsRow,
)


@pytest.mark.asyncio
async def test_create_notification_and_settings_roundtrip(db_session_with_schema: AsyncSession) -> None:
    settings = SettingsRow(
        id=1,
        default_llm_provider="anthropic",
        recruiter_email="me@example.com",
    )
    db_session_with_schema.add(settings)
    await db_session_with_schema.commit()

    n = Notification(
        application_id=None,
        channel=NotificationChannel.EMAIL,
        provider=NotificationProvider.SMTP,
        subject="hi",
        body="body",
        status=NotificationStatus.DRAFT,
    )
    db_session_with_schema.add(n)
    await db_session_with_schema.commit()
    assert n.id is not None


@pytest.mark.asyncio
async def test_event_log_can_be_inserted(db_session_with_schema: AsyncSession) -> None:
    e = EventLog(event_type="application.scored", payload={"score": 87})
    db_session_with_schema.add(e)
    await db_session_with_schema.commit()
    assert e.id is not None
