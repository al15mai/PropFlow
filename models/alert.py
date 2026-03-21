from sqlmodel import SQLModel, Field

from .base import generate_id


class Alert(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True)

    # type can be: Contract, Payment, or Maintenance
    type: str
    message: str
    # severity can be: high, medium, or low
    severity: str
    date: str
