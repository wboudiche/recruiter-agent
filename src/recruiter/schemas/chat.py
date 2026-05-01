from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class UndoRequest(BaseModel):
    undo_token: str = Field(min_length=1)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    role: str
    content: str | None
    tool_calls: list | None
    tool_call_id: str | None
    tool_name: str | None
    tool_result: dict | None
    created_at: datetime
