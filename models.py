"""
Backward compatibility module - re-exports from PropFlow.models package.
All actual model definitions are in PropFlow/models/ subdirectory.
"""

from models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    User,
    Project,
    UserProject,
    Alert,
    LandlordSettings,
    TransactionType,
    ExpenseCategory,
    IncomeCategory,
    UtilityType,
    PaymentMethod,
    PropertyType,
    PropertyStatus,
    TenantStatus,
    MaintenancePriority,
    MaintenanceStatus,
    generate_id,
)

__all__ = [
    "Property",
    "Tenant",
    "Transaction",
    "MaintenanceRequest",
    "User",
    "Project",
    "UserProject",
    "Alert",
    "LandlordSettings",
    "TransactionType",
    "ExpenseCategory",
    "IncomeCategory",
    "UtilityType",
    "PaymentMethod",
    "PropertyType",
    "PropertyStatus",
    "TenantStatus",
    "MaintenancePriority",
    "MaintenanceStatus",
    "generate_id",
]
