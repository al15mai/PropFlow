from pydantic import BaseModel
from typing import Optional, Literal

PropertyStatus = Literal["Occupied", "Vacant", "Maintenance"]
PropertyType = Literal["Rental", "Personal"]


class Property(BaseModel):
    id: str
    address: str
    unitNumber: str
    rooms: int
    rentAmount: float
    currency: str
    status: PropertyStatus
    type: PropertyType
    image: Optional[str] = None


class Tenant(BaseModel):
    id: str
    propertyId: str
    name: str
    email: str
    phone: str
    leaseStart: str
    leaseEnd: str
    deposit: float
    status: Literal["Active", "Past", "Late"]


TransactionType = Literal["Income", "Expense"]
ExpenseCategory = Literal[
    "Maintenance",
    "Tax",
    "Insurance",
    "Utilities",
    "Mortgage",
    "Other",
]
PaymentMethod = Literal["Cash", "Transfer", "Check"]


class Transaction(BaseModel):
    id: str
    date: str
    amount: float
    type: TransactionType
    category: Optional[ExpenseCategory] = None
    subcategory: Optional[str] = None
    description: str
    propertyId: Optional[str] = None
    tenantId: Optional[str] = None
    paymentMethod: PaymentMethod
    isReimbursable: Optional[bool] = False
    attachmentUrl: Optional[str] = None
    isPaid: Optional[bool] = False


RequestPriority = Literal["Low", "Medium", "High", "Emergency"]
RequestStatus = Literal["Open", "In Progress", "Resolved"]


class MaintenanceRequest(BaseModel):
    id: str
    propertyId: str
    tenantId: Optional[str] = None
    title: str
    description: str
    priority: RequestPriority
    status: RequestStatus
    dateReported: str


class Alert(BaseModel):
    id: str
    type: Literal["Contract", "Payment", "Maintenance"]
    message: str
    severity: Literal["high", "medium", "low"]
    date: str


class LandlordSettings(BaseModel):
    displayName: str
    email: str
    phone: str
    companyName: str
    currency: str
    language: Literal["en", "ro"]
