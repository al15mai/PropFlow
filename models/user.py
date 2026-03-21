from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field

from .base import generate_id

if TYPE_CHECKING:
    from .project import Project


class User(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    email: str = Field(index=True, nullable=False)
    name: Optional[str] = None
    hashed_password: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationship is defined in Project model to avoid circular imports
    # Use: user.projects for forward relationship from Project.users
