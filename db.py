"""
Database abstraction layer for PropFlow backend using SQLModel ORM.
Implements multi-tenant data isolation by enforcing project_id filtering on all operations.
Separates database concerns from API routing logic.
"""

from typing import Optional, List
from abc import ABC, abstractmethod
from sqlmodel import Session, select

# Import SQLModel models from models package
from PropFlow.models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    Alert,
    LandlordSettings,
)


class DatabaseInterface(ABC):
    """Abstract interface for database operations with multi-tenant support."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema."""
        pass

    # Properties
    @abstractmethod
    def list_properties(
        self,
        session: Session,
        project_id: str,
        type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Property]:
        pass

    @abstractmethod
    def create_property(self, session: Session, p: Property) -> Property:
        pass

    @abstractmethod
    def update_property(
        self, session: Session, id: str, p: Property, project_id: str
    ) -> Property:
        pass

    @abstractmethod
    def delete_property(self, session: Session, id: str, project_id: str) -> None:
        pass

    # Tenants
    @abstractmethod
    def list_tenants(
        self,
        session: Session,
        project_id: str,
        propertyId: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Tenant]:
        pass

    @abstractmethod
    def create_tenant(self, session: Session, t: Tenant) -> Tenant:
        pass

    @abstractmethod
    def update_tenant(
        self, session: Session, id: str, t: Tenant, project_id: str
    ) -> Tenant:
        pass

    @abstractmethod
    def delete_tenant(self, session: Session, id: str, project_id: str) -> None:
        pass

    # Transactions
    @abstractmethod
    def list_transactions(
        self, session: Session, project_id: str, **filters
    ) -> List[Transaction]:
        pass

    @abstractmethod
    def create_transaction(self, session: Session, tx: Transaction) -> Transaction:
        pass

    @abstractmethod
    def update_transaction(
        self, session: Session, id: str, tx: Transaction, project_id: str
    ) -> Transaction:
        pass

    @abstractmethod
    def delete_transaction(self, session: Session, id: str, project_id: str) -> None:
        pass

    # Maintenance
    @abstractmethod
    def list_maintenance(
        self, session: Session, project_id: str, **filters
    ) -> List[MaintenanceRequest]:
        pass

    @abstractmethod
    def create_maintenance(
        self, session: Session, req: MaintenanceRequest
    ) -> MaintenanceRequest:
        pass

    @abstractmethod
    def update_maintenance(
        self, session: Session, id: str, req: MaintenanceRequest, project_id: str
    ) -> MaintenanceRequest:
        pass

    @abstractmethod
    def delete_maintenance(self, session: Session, id: str, project_id: str) -> None:
        pass

    # Alerts
    @abstractmethod
    def list_alerts(self, session: Session, project_id: str) -> List[Alert]:
        pass

    @abstractmethod
    def create_alert(self, session: Session, alert: Alert) -> Alert:
        pass

    @abstractmethod
    def delete_alert(self, session: Session, id: str, project_id: str) -> None:
        pass

    # Settings
    @abstractmethod
    def get_settings(
        self, session: Session, project_id: str
    ) -> Optional[LandlordSettings]:
        pass

    @abstractmethod
    def save_settings(self, session: Session, s: LandlordSettings) -> LandlordSettings:
        pass


class SQLModelDatabase(DatabaseInterface):
    """Database implementation using SQLModel ORM for multi-tenant operations."""

    def initialize(self) -> None:
        """Initialize database tables (handled by database.py on app startup)."""
        pass

    # --- Properties ---
    def list_properties(
        self,
        session: Session,
        project_id: str,
        type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Property]:
        """List properties filtered by project_id and optional type/status."""
        stmt = select(Property).where(Property.projectId == project_id)

        if type:
            stmt = stmt.where(Property.type == type)
        if status:
            stmt = stmt.where(Property.status == status)

        return list(session.exec(stmt).all())

    def create_property(self, session: Session, p: Property) -> Property:
        """Create a new property."""
        session.add(p)
        session.commit()
        session.refresh(p)
        return p

    def update_property(
        self, session: Session, id: str, p: Property, project_id: str
    ) -> Property:
        """Update a property (verifies it belongs to the project)."""
        stmt = select(Property).where(
            (Property.id == id) & (Property.projectId == project_id)
        )
        db_property = session.exec(stmt).first()

        if not db_property:
            raise ValueError(f"Property {id} not found in project {project_id}")

        db_property.address = p.address
        db_property.unitNumber = p.unitNumber
        db_property.rooms = p.rooms
        db_property.rentAmount = p.rentAmount
        db_property.currency = p.currency
        db_property.status = p.status
        db_property.type = p.type
        db_property.image = p.image
        db_property.purchasePrice = p.purchasePrice
        db_property.purchaseDate = p.purchaseDate

        session.add(db_property)
        session.commit()
        session.refresh(db_property)
        return db_property

    def delete_property(self, session: Session, id: str, project_id: str) -> None:
        """Delete a property (verifies it belongs to the project)."""
        stmt = select(Property).where(
            (Property.id == id) & (Property.projectId == project_id)
        )
        db_property = session.exec(stmt).first()

        if not db_property:
            raise ValueError(f"Property {id} not found in project {project_id}")

        session.delete(db_property)
        session.commit()

    # --- Tenants ---
    def list_tenants(
        self,
        session: Session,
        project_id: str,
        propertyId: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Tenant]:
        """List tenants filtered by project_id and optional property/status."""
        stmt = select(Tenant).where(Tenant.projectId == project_id)

        if propertyId:
            stmt = stmt.where(Tenant.propertyId == propertyId)
        if status:
            stmt = stmt.where(Tenant.status == status)

        return list(session.exec(stmt).all())

    def create_tenant(self, session: Session, t: Tenant) -> Tenant:
        """Create a new tenant."""
        session.add(t)
        session.commit()
        session.refresh(t)
        return t

    def update_tenant(
        self, session: Session, id: str, t: Tenant, project_id: str
    ) -> Tenant:
        """Update a tenant (verifies it belongs to the project)."""
        stmt = select(Tenant).where(
            (Tenant.id == id) & (Tenant.projectId == project_id)
        )
        db_tenant = session.exec(stmt).first()

        if not db_tenant:
            raise ValueError(f"Tenant {id} not found in project {project_id}")

        db_tenant.propertyId = t.propertyId
        db_tenant.name = t.name
        db_tenant.email = t.email
        db_tenant.phone = t.phone
        db_tenant.leaseStart = t.leaseStart
        db_tenant.leaseEnd = t.leaseEnd
        db_tenant.deposit = t.deposit
        db_tenant.status = t.status

        session.add(db_tenant)
        session.commit()
        session.refresh(db_tenant)
        return db_tenant

    def delete_tenant(self, session: Session, id: str, project_id: str) -> None:
        """Delete a tenant (verifies it belongs to the project)."""
        stmt = select(Tenant).where(
            (Tenant.id == id) & (Tenant.projectId == project_id)
        )
        db_tenant = session.exec(stmt).first()

        if not db_tenant:
            raise ValueError(f"Tenant {id} not found in project {project_id}")

        session.delete(db_tenant)
        session.commit()

    # --- Transactions ---
    def list_transactions(
        self, session: Session, project_id: str, **filters
    ) -> List[Transaction]:
        """List transactions filtered by project_id and optional filters."""
        stmt = select(Transaction).where(Transaction.projectId == project_id)

        if startDate := filters.get("startDate"):
            stmt = stmt.where(Transaction.date >= startDate)
        if endDate := filters.get("endDate"):
            stmt = stmt.where(Transaction.date <= endDate)
        if type_ := filters.get("type"):
            stmt = stmt.where(Transaction.type == type_)
        if propertyId := filters.get("propertyId"):
            stmt = stmt.where(Transaction.propertyId == propertyId)
        if tenantId := filters.get("tenantId"):
            stmt = stmt.where(Transaction.tenantId == tenantId)

        return list(session.exec(stmt).all())

    def create_transaction(self, session: Session, tx: Transaction) -> Transaction:
        """Create a new transaction."""
        session.add(tx)
        session.commit()
        session.refresh(tx)
        return tx

    def update_transaction(
        self, session: Session, id: str, tx: Transaction, project_id: str
    ) -> Transaction:
        """Update a transaction (verifies it belongs to the project)."""
        stmt = select(Transaction).where(
            (Transaction.id == id) & (Transaction.projectId == project_id)
        )
        db_tx = session.exec(stmt).first()

        if not db_tx:
            raise ValueError(f"Transaction {id} not found in project {project_id}")

        db_tx.date = tx.date
        db_tx.amount = tx.amount
        db_tx.type = tx.type
        db_tx.category = tx.category
        db_tx.subcategory = tx.subcategory
        db_tx.description = tx.description
        db_tx.propertyId = tx.propertyId
        db_tx.tenantId = tx.tenantId
        db_tx.paymentMethod = tx.paymentMethod
        db_tx.isReimbursable = tx.isReimbursable
        db_tx.attachmentUrl = tx.attachmentUrl
        db_tx.isPaid = tx.isPaid
        db_tx.maintenanceId = tx.maintenanceId

        session.add(db_tx)
        session.commit()
        session.refresh(db_tx)
        return db_tx

    def delete_transaction(self, session: Session, id: str, project_id: str) -> None:
        """Delete a transaction (verifies it belongs to the project)."""
        stmt = select(Transaction).where(
            (Transaction.id == id) & (Transaction.projectId == project_id)
        )
        db_tx = session.exec(stmt).first()

        if not db_tx:
            raise ValueError(f"Transaction {id} not found in project {project_id}")

        session.delete(db_tx)
        session.commit()

    # --- Maintenance ---
    def list_maintenance(
        self, session: Session, project_id: str, **filters
    ) -> List[MaintenanceRequest]:
        """List maintenance requests filtered by project_id and optional filters."""
        stmt = select(MaintenanceRequest).where(
            MaintenanceRequest.projectId == project_id
        )

        if status := filters.get("status"):
            stmt = stmt.where(MaintenanceRequest.status == status)
        if propertyId := filters.get("propertyId"):
            stmt = stmt.where(MaintenanceRequest.propertyId == propertyId)
        if tenantId := filters.get("tenantId"):
            stmt = stmt.where(MaintenanceRequest.tenantId == tenantId)

        return list(session.exec(stmt).all())

    def create_maintenance(
        self, session: Session, req: MaintenanceRequest
    ) -> MaintenanceRequest:
        """Create a new maintenance request."""
        session.add(req)
        session.commit()
        session.refresh(req)
        return req

    def update_maintenance(
        self, session: Session, id: str, req: MaintenanceRequest, project_id: str
    ) -> MaintenanceRequest:
        """Update a maintenance request (verifies it belongs to the project)."""
        stmt = select(MaintenanceRequest).where(
            (MaintenanceRequest.id == id) & (MaintenanceRequest.projectId == project_id)
        )
        db_req = session.exec(stmt).first()

        if not db_req:
            raise ValueError(
                f"Maintenance request {id} not found in project {project_id}"
            )

        db_req.propertyId = req.propertyId
        db_req.tenantId = req.tenantId
        db_req.title = req.title
        db_req.description = req.description
        db_req.priority = req.priority
        db_req.status = req.status
        db_req.dateReported = req.dateReported
        db_req.history = req.history
        db_req.comments = req.comments

        session.add(db_req)
        session.commit()
        session.refresh(db_req)
        return db_req

    def delete_maintenance(self, session: Session, id: str, project_id: str) -> None:
        """Delete a maintenance request (verifies it belongs to the project)."""
        stmt = select(MaintenanceRequest).where(
            (MaintenanceRequest.id == id) & (MaintenanceRequest.projectId == project_id)
        )
        db_req = session.exec(stmt).first()

        if not db_req:
            raise ValueError(
                f"Maintenance request {id} not found in project {project_id}"
            )

        session.delete(db_req)
        session.commit()

    # --- Alerts ---
    def list_alerts(self, session: Session, project_id: str) -> List[Alert]:
        """List alerts for a project."""
        stmt = select(Alert).where(Alert.projectId == project_id)
        return list(session.exec(stmt).all())

    def create_alert(self, session: Session, alert: Alert) -> Alert:
        """Create a new alert."""
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert

    def delete_alert(self, session: Session, id: str, project_id: str) -> None:
        """Delete an alert (verifies it belongs to the project)."""
        stmt = select(Alert).where((Alert.id == id) & (Alert.projectId == project_id))
        db_alert = session.exec(stmt).first()

        if not db_alert:
            raise ValueError(f"Alert {id} not found in project {project_id}")

        session.delete(db_alert)
        session.commit()

    # --- Settings ---
    def get_settings(
        self, session: Session, project_id: str
    ) -> Optional[LandlordSettings]:
        """Get settings for a project."""
        stmt = select(LandlordSettings).where(LandlordSettings.projectId == project_id)
        return session.exec(stmt).first()

    def save_settings(self, session: Session, s: LandlordSettings) -> LandlordSettings:
        """Create or update settings for a project."""
        # Check if settings already exist
        existing = self.get_settings(session, s.projectId)

        if existing:
            existing.displayName = s.displayName
            existing.email = s.email
            existing.phone = s.phone
            existing.companyName = s.companyName
            existing.currency = s.currency
            existing.language = s.language
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        else:
            session.add(s)
            session.commit()
            session.refresh(s)
            return s
