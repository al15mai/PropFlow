from typing import Optional, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from .base import generate_id
from .enums import TransactionType, ExpenseCategory, PaymentMethod

if TYPE_CHECKING:
    from .property import Property
    from .tenant import Tenant


class Transaction(SQLModel, table=True):
    id: str = Field(default_factory=generate_id, primary_key=True)
    projectId: str = Field(foreign_key="project.id", index=True)

    date: str
    amount: float
    type: TransactionType
    category: Optional[ExpenseCategory] = None
    subcategory: Optional[str] = None
    description: Optional[str] = None
    propertyId: Optional[str] = Field(
        default=None, foreign_key="property.id", index=True
    )
    tenantId: Optional[str] = Field(default=None, foreign_key="tenant.id", index=True)
    paymentMethod: Optional[PaymentMethod] = None
    isReimbursable: Optional[bool] = False
    attachmentUrl: Optional[str] = None
    isPaid: Optional[bool] = False
    maintenanceId: Optional[str] = Field(
        default=None, foreign_key="maintenancerequest.id"
    )

    property: Optional["Property"] = Relationship(back_populates="transactions")
    tenant: Optional["Tenant"] = Relationship()
