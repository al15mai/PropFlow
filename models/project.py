from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .base import generate_id
from .associations import UserProject

if TYPE_CHECKING:
    from .user import User
    from .property import Property


class Project(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    name: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    users: List["User"] = Relationship(link_model=UserProject)
    properties: List["Property"] = Relationship(back_populates="project")
