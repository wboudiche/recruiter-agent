from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_app_created", "application_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="chat_message_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(String)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(64))
    tool_result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
