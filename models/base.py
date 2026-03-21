from datetime import datetime
from uuid import uuid4

from sqlmodel import SQLModel, Field


def generate_id() -> str:
    return str(uuid4())


class IDMixin(SQLModel):
    id: str = Field(default_factory=generate_id, primary_key=True, index=True)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
