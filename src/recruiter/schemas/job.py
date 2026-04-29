from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CriteriaItem(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    criteria: list[CriteriaItem] = Field(default_factory=list)


class JobUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    criteria: list[CriteriaItem] | None = None
    status: str | None = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    criteria: list[CriteriaItem]
    status: str
    created_at: datetime
    updated_at: datetime
