from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Literal

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
    # Workspace this belongs to (task D4b). Null = legacy / shared across projects.
    projectId: Optional[str] = None

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
    # Day of the month (1-28) rent is due for this tenant, used by the alerts
    # engine's rent-late check (task E1). Null -> treated as the 1st, matching the
    # rent obligations allocateTenantFunds() dates to `<month>-01`.
    rentDueDay: Optional[int] = None
    # Workspace this belongs to (task D4b). Null = legacy / shared across projects.
    projectId: Optional[str] = None
    # Tenant login (task D1f). `hasLogin` is a read-only convenience the API fills
    # in (true once a password hash exists); `mustReset` forces a password change
    # on first sign-in. The password hash itself NEVER rides on this model — it
    # lives only in `tenants.passwordHash` and is read by `db.get_tenant_auth*`.
    hasLogin: Optional[bool] = None
    mustReset: Optional[bool] = None

    class Config:
        extra = "ignore"


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
    isPaid: Optional[bool] = False
    # Multi-currency (task A4). Legacy rows leave these null and are treated as base (RON).
    currency: Optional[str] = None          # currency `amount` is denominated in
    fxRate: Optional[float] = None          # RON (base) per 1 unit of `currency`
    amountBase: Optional[float] = None      # amount * fxRate, i.e. the value in RON
    # Links an expense to the maintenance request it paid for (task E3). Null for
    # everything that isn't a repair cost.
    maintenanceId: Optional[str] = None

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
    # Workspace this belongs to (task D4b). Null = legacy / shared across projects.
    projectId: Optional[str] = None

    class Config:
        extra = "ignore"


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


DocumentKind = Literal["invoice", "receipt", "bill", "other"]
DocumentStorage = Literal["file", "link"]


class Document(BaseModel):
    """An invoice / receipt / bill attached to a transaction (task E8).

    One transaction -> many documents. Tenant/property are NOT stored here; the
    tenant sees a document because it hangs off one of their transactions.
    `transactionId` is null only for a short-lived 'pending' upload (E7 scan-first).
    """
    id: str
    transactionId: Optional[str] = None
    kind: DocumentKind = "other"
    filename: str
    mime: Optional[str] = None
    size: Optional[int] = None
    storage: DocumentStorage
    path: Optional[str] = None   # relative to the uploads dir, when storage == "file"
    url: Optional[str] = None    # the original link, when storage == "link"
    sha256: Optional[str] = None
    note: Optional[str] = ""
    createdAt: str

    class Config:
        extra = "ignore"


class InvoiceTemplate(BaseModel):
    """A per-vendor invoice-parsing rule authored in the app (task E7).

    `spec` is the rule itself: {vendor, match: [phrase], category?, subcategory?,
    fields: {name: {after, kind}}}. Its `after`/`match` phrases are treated as
    literal text (not regex) so a user can't inject a catastrophic pattern.
    `source` is "user" (hand-authored) or "auto" (saved from an LLM field-locate).
    """
    id: str = ""          # server-assigned on create
    vendor: str
    spec: Dict[str, Any]
    source: Literal["user", "auto"] = "user"
    # Workspace this belongs to (task D4b). Null = shared across projects.
    projectId: Optional[str] = None
    createdAt: str = ""    # server-assigned on create

    class Config:
        extra = "ignore"


class InvoiceExtraction(BaseModel):
    """Result of running the extraction pipeline over one invoice (task E7).

    `parsed` matches the frontend `ParsedInvoice` shape; `needsReview` lists the
    fields the user must confirm (low confidence or not found); `dueDate` is a
    bonus the templates pull that `ParsedInvoice` doesn't carry.
    """
    parsed: Dict[str, Any]
    needsReview: List[str] = []
    templateVendor: Optional[str] = None
    dueDate: Optional[str] = None
    source: str = "template"  # "template" | "model" | "manual"


# --- Auth / multi-tenant (task D1) ------------------------------------------

Role = Literal["owner", "member"]


class User(BaseModel):
    """A person who can log in. The password hash NEVER appears here — it lives
    only in the `users` table and is read by `db.get_user_auth()`."""
    id: str
    email: str
    name: str
    avatar: Optional[str] = None
    createdAt: str

    class Config:
        extra = "ignore"


class Project(BaseModel):
    """A workspace. Existing NULL-`projectId` data is 'shared' and shows in every
    project (D4b lenient filter); D1 seeds one project that owns it."""
    id: str
    name: str
    ownerId: str
    currency: str = "RON"
    createdAt: str
    members: List[str] = []  # user ids — populated on read from `project_members`

    class Config:
        extra = "ignore"


class Invite(BaseModel):
    """A pending membership. The raw token is shown to the owner exactly once
    (embedded in the invite link) and stored only hashed."""
    id: str
    email: str
    name: Optional[str] = None
    projectId: str
    role: Role = "member"
    createdAt: str
    acceptedAt: Optional[str] = None

    class Config:
        extra = "ignore"


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateInviteRequest(BaseModel):
    email: str
    name: Optional[str] = None
    projectId: str
    role: Role = "member"


class AcceptInviteRequest(BaseModel):
    token: str
    name: Optional[str] = None
    password: str


class AuthResponse(BaseModel):
    token: str
    user: User
    projects: List[Project] = []


# --- Tenant authentication (task D1f) ---------------------------------------

class TenantLoginRequest(BaseModel):
    """Tenant sign-in: `identifier` is matched against the tenant's email OR
    phone (phone is normalized — see `auth.normalize_phone`)."""
    identifier: str
    password: str


class TenantChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


class TenantAuthResponse(BaseModel):
    """What a tenant login / `/auth/me` (tenant token) returns. Deliberately
    minimal — the tenant's full record comes from `GET /tenants` (scoped)."""
    token: str
    tenant: Tenant
    mustReset: bool = False


class TenantPasswordReset(BaseModel):
    """The one-time plaintext handed back to the landlord after creating a tenant
    or resetting its password. Never stored, never logged."""
    tenantId: str
    password: str


class TenantCreateResponse(Tenant):
    """`POST /tenants` returns the tenant PLUS the one-time generated password so
    the landlord can hand it over. `initialPassword` is never persisted."""
    initialPassword: str
