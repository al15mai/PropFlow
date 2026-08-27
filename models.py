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
    # RON (landlord base) per 1 unit of `currency`. None / 1.0 for RON properties.
    # Used to value this property's rent obligation in base currency (task A4).
    fxRate: Optional[float] = None

    class Config:
        extra = "ignore"


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
    "Rent",
    "Deposit",
]
PaymentMethod = Literal["Cash", "Transfer", "Check", "System"]


class Transaction(BaseModel):
    id: str
    date: str
    amount: float
    type: TransactionType
    category: Optional[ExpenseCategory] = None
    subcategory: Optional[str] = None
    description: Optional[str] = ""
    projectId: Optional[str] = None
    propertyId: Optional[str] = None
    tenantId: Optional[str] = None
    paymentMethod: PaymentMethod
    isReimbursable: Optional[bool] = False
    attachmentUrl: Optional[str] = None
    isPaid: Optional[bool] = False
    # Multi-currency (task A4). Legacy rows leave these null and are treated as base (RON).
    currency: Optional[str] = None          # currency `amount` is denominated in
    fxRate: Optional[float] = None          # RON (base) per 1 unit of `currency`
    amountBase: Optional[float] = None      # amount * fxRate, i.e. the value in RON

    class Config:
        extra = "ignore"


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
