from sqlmodel import SQLModel, Field

from .base import generate_id


class LandlordSettings(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True, unique=True)

    displayName: str
    email: str
    phone: str
    companyName: str
    currency: str
    # language can be: en (English) or ro (Romanian)
    language: str = Field(default="en")
