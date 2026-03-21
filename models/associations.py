"""
Association tables and models for many-to-many relationships.
Defined separately to avoid circular imports.
"""

from typing import Optional

from sqlmodel import SQLModel, Field


class UserProject(SQLModel, table=True):
    """Association table linking users to projects with role information."""

    user_id: str = Field(foreign_key="user.id", primary_key=True)
    project_id: str = Field(foreign_key="project.id", primary_key=True)
    role: Optional[str] = None
