from typing import Optional, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .base import generate_id
from .enums import TenantStatus

if TYPE_CHECKING:
    from .property import Property


class Tenant(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True)
    propertyId: str = Field(foreign_key="property.id", index=True)

    name: str
    email: str
    phone: Optional[str] = None
    leaseStart: Optional[str] = None
    leaseEnd: Optional[str] = None
    deposit: Optional[float] = None
    status: TenantStatus = Field(
        sa_column_kwargs={"default": TenantStatus.ACTIVE.value}
    )

    property: "Property" = Relationship(back_populates="tenants")
