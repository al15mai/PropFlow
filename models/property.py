from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .base import generate_id
from .enums import PropertyStatus, PropertyType

if TYPE_CHECKING:
    from .project import Project
    from .tenant import Tenant
    from .transaction import Transaction


class Property(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True)

    address: str
    unitNumber: Optional[str] = None
    rooms: Optional[int] = None
    rentAmount: Optional[float] = None
    currency: Optional[str] = None
    status: PropertyStatus = Field(
        sa_column_kwargs={"default": PropertyStatus.OCCUPIED.value}
    )
    type: PropertyType = Field(sa_column_kwargs={"default": PropertyType.RENTAL.value})
    image: Optional[str] = None
    purchasePrice: Optional[float] = None
    purchaseDate: Optional[str] = None

    project: "Project" = Relationship(back_populates="properties")
    tenants: List["Tenant"] = Relationship(back_populates="property")
    transactions: List["Transaction"] = Relationship(back_populates="property")
