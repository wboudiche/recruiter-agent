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
