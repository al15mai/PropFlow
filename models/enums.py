from enum import Enum


class TransactionType(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"


class ExpenseCategory(str, Enum):
    MAINTENANCE = "Maintenance"
    TAX = "Tax"
    INSURANCE = "Insurance"
    UTILITIES = "Utilities"
    MORTGAGE = "Mortgage"
    OTHER = "Other"
    RENT = "Rent"
    DEPOSIT = "Deposit"
    RENOVATION = "Renovation"


class IncomeCategory(str, Enum):
    RENT = "Rent"
    DEPOSIT = "Deposit"
    UTILITIES = "Utilities"
    OTHER = "Other"


class UtilityType(str, Enum):
    ELECTRICITY = "Electricity"
    WATER = "Water"
    GAS = "Gas"
    INTERNET = "Internet"
    TRASH = "Trash"
    RESIDENTS_ASSOCIATION_TAX = "Residents Association Tax"
    OTHER = "Other"


class PaymentMethod(str, Enum):
    CASH = "Cash"
    TRANSFER = "Transfer"
    CHECK = "Check"


class PropertyType(str, Enum):
    RENTAL = "Rental"
    PERSONAL = "Personal"


class PropertyStatus(str, Enum):
    OCCUPIED = "Occupied"
    VACANT = "Vacant"
    MAINTENANCE = "Maintenance"


class TenantStatus(str, Enum):
    ACTIVE = "Active"
    PAST = "Past"
    LATE = "Late"


class MaintenancePriority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    EMERGENCY = "Emergency"


class MaintenanceStatus(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
