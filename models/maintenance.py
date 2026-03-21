from typing import Optional, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .base import generate_id
from .enums import MaintenancePriority, MaintenanceStatus

if TYPE_CHECKING:
    from .property import Property


class MaintenanceRequest(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True)
    propertyId: str = Field(foreign_key="property.id", index=True)
    tenantId: Optional[str] = Field(default=None, foreign_key="tenant.id", index=True)

    title: str
    description: str
    priority: MaintenancePriority
    status: MaintenanceStatus
    dateReported: str

    # For simplicity (SQLite) store history/comments as JSON string
    history: Optional[str] = None
    comments: Optional[str] = None

    property: "Property" = Relationship()
