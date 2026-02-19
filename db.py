import sqlite3
from sqlite3 import Connection, Cursor
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from backend.models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    Alert,
    LandlordSettings,
)


class DatabaseInterface(ABC):
    @abstractmethod
    def initialize(self) -> None:
        pass

    # Properties
    @abstractmethod
    def list_properties(
        self, type: Optional[str] = None, status: Optional[str] = None
    ) -> List[Property]:
        pass

    @abstractmethod
    def create_property(self, p: Property) -> Property:
        pass

    @abstractmethod
    def update_property(self, id: str, p: Property) -> Property:
        pass

    @abstractmethod
    def delete_property(self, id: str) -> None:
        pass

    # Tenants
    @abstractmethod
    def list_tenants(
        self, propertyId: Optional[str] = None, status: Optional[str] = None
    ) -> List[Tenant]:
        pass

    @abstractmethod
    def create_tenant(self, t: Tenant) -> Tenant:
        pass

    @abstractmethod
    def update_tenant(self, id: str, t: Tenant) -> Tenant:
        pass

    @abstractmethod
    def delete_tenant(self, id: str) -> None:
        pass

    # Transactions
    @abstractmethod
    def list_transactions(self, **filters) -> List[Transaction]:
        pass

    @abstractmethod
    def create_transaction(self, tx: Transaction) -> Transaction:
        pass

    @abstractmethod
    def update_transaction(self, id: str, tx: Transaction) -> Transaction:
        pass

    @abstractmethod
    def delete_transaction(self, id: str) -> None:
        pass

    # Maintenance
    @abstractmethod
    def list_maintenance(self, **filters) -> List[MaintenanceRequest]:
        pass

    @abstractmethod
    def create_maintenance(self, req: MaintenanceRequest) -> MaintenanceRequest:
        pass

    @abstractmethod
    def update_maintenance(
        self, id: str, req: MaintenanceRequest
    ) -> MaintenanceRequest:
        pass

    @abstractmethod
    def delete_maintenance(self, id: str) -> None:
        pass

    # Alerts
    @abstractmethod
    def list_alerts(self) -> List[Alert]:
        pass

    # Settings
    @abstractmethod
    def save_settings(self, s: LandlordSettings) -> LandlordSettings:
        pass


class SQLiteDatabase(DatabaseInterface):
    def __init__(self, path: str | Path = "data.db"):
        self.path = str(path)
        self.conn: Optional[Connection] = None

    def _connect(self) -> None:
        if self.conn is None:
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def _cursor(self) -> Cursor:
        """Return a DB cursor ensuring the connection is initialized.

        This avoids static type checkers warning about `conn` possibly being None.
        """
        self._connect()
        assert self.conn is not None
        return self.conn.cursor()

    def initialize(self) -> None:
        cur = self._cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS properties (
                id TEXT PRIMARY KEY,
                address TEXT,
                unitNumber TEXT,
                rooms INTEGER,
                rentAmount REAL,
                currency TEXT,
                status TEXT,
                type TEXT,
                image TEXT
            )"""
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                propertyId TEXT,
                name TEXT,
                email TEXT,
                phone TEXT,
                leaseStart TEXT,
                leaseEnd TEXT,
                deposit REAL,
                status TEXT
            )"""
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                date TEXT,
                amount REAL,
                type TEXT,
                category TEXT,
                subcategory TEXT,
                description TEXT,
                propertyId TEXT,
                tenantId TEXT,
                paymentMethod TEXT,
                isReimbursable INTEGER,
                attachmentUrl TEXT,
                isPaid INTEGER
            )"""
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance (
                id TEXT PRIMARY KEY,
                propertyId TEXT,
                tenantId TEXT,
                title TEXT,
                description TEXT,
                priority TEXT,
                status TEXT,
                dateReported TEXT
            )"""
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                type TEXT,
                message TEXT,
                severity TEXT,
                date TEXT
            )"""
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                displayName TEXT,
                email TEXT,
                phone TEXT,
                companyName TEXT,
                currency TEXT,
                language TEXT
            )"""
        )
        assert self.conn is not None
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    # --- Properties ---
    def list_properties(
        self, type: Optional[str] = None, status: Optional[str] = None
    ) -> List[Property]:
        cur = self._cursor()
        q = "SELECT * FROM properties"
        clauses = []
        params: List[Any] = []
        if type:
            clauses.append("type = ?")
            params.append(type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Property(**self._row_to_dict(r)) for r in rows]

    def create_property(self, p: Property) -> Property:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO properties (id,address,unitNumber,rooms,rentAmount,currency,status,type,image) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                p.id,
                p.address,
                p.unitNumber,
                p.rooms,
                p.rentAmount,
                p.currency,
                p.status,
                p.type,
                p.image,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return p

    def update_property(self, id: str, p: Property) -> Property:
        cur = self._cursor()
        cur.execute(
            "UPDATE properties SET address=?,unitNumber=?,rooms=?,rentAmount=?,currency=?,status=?,type=?,image=? WHERE id=?",
            (
                p.address,
                p.unitNumber,
                p.rooms,
                p.rentAmount,
                p.currency,
                p.status,
                p.type,
                p.image,
                id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError("Property not found")
        assert self.conn is not None
        self.conn.commit()
        return p

    def delete_property(self, id: str) -> None:
        cur = self._cursor()
        cur.execute("DELETE FROM properties WHERE id=?", (id,))
        assert self.conn is not None
        self.conn.commit()

    # --- Tenants ---
    def list_tenants(
        self, propertyId: Optional[str] = None, status: Optional[str] = None
    ) -> List[Tenant]:
        cur = self._cursor()
        q = "SELECT * FROM tenants"
        clauses = []
        params: List[Any] = []
        if propertyId:
            clauses.append("propertyId = ?")
            params.append(propertyId)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Tenant(**self._row_to_dict(r)) for r in rows]

    def create_tenant(self, t: Tenant) -> Tenant:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO tenants (id,propertyId,name,email,phone,leaseStart,leaseEnd,deposit,status) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                t.id,
                t.propertyId,
                t.name,
                t.email,
                t.phone,
                t.leaseStart,
                t.leaseEnd,
                t.deposit,
                t.status,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return t

    def update_tenant(self, id: str, t: Tenant) -> Tenant:
        cur = self._cursor()
        cur.execute(
            "UPDATE tenants SET propertyId=?,name=?,email=?,phone=?,leaseStart=?,leaseEnd=?,deposit=?,status=? WHERE id=?",
            (
                t.propertyId,
                t.name,
                t.email,
                t.phone,
                t.leaseStart,
                t.leaseEnd,
                t.deposit,
                t.status,
                id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError("Tenant not found")
        assert self.conn is not None
        self.conn.commit()
        return t

    def delete_tenant(self, id: str) -> None:
        cur = self._cursor()
        cur.execute("DELETE FROM tenants WHERE id=?", (id,))
        assert self.conn is not None
        self.conn.commit()

    # --- Transactions ---
    def list_transactions(self, **filters) -> List[Transaction]:
        cur = self._cursor()
        q = "SELECT * FROM transactions"
        clauses = []
        params: List[Any] = []
        for key in ("startDate", "endDate", "type", "propertyId", "tenantId"):
            if key in filters and filters[key] is not None:
                if key == "startDate":
                    clauses.append("date >= ?")
                elif key == "endDate":
                    clauses.append("date <= ?")
                else:
                    clauses.append(f"{key} = ?")
                params.append(filters[key])
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Transaction(**self._row_to_dict(r)) for r in rows]

    def create_transaction(self, tx: Transaction) -> Transaction:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO transactions (id,date,amount,type,category,subcategory,description,propertyId,tenantId,paymentMethod,isReimbursable,attachmentUrl,isPaid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tx.id,
                tx.date,
                tx.amount,
                tx.type,
                tx.category,
                tx.subcategory,
                tx.description,
                tx.propertyId,
                tx.tenantId,
                tx.paymentMethod,
                int(bool(tx.isReimbursable)),
                tx.attachmentUrl,
                int(bool(tx.isPaid)),
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return tx

    def update_transaction(self, id: str, tx: Transaction) -> Transaction:
        cur = self._cursor()
        cur.execute(
            "UPDATE transactions SET date=?,amount=?,type=?,category=?,subcategory=?,description=?,propertyId=?,tenantId=?,paymentMethod=?,isReimbursable=?,attachmentUrl=?,isPaid=? WHERE id=?",
            (
                tx.date,
                tx.amount,
                tx.type,
                tx.category,
                tx.subcategory,
                tx.description,
                tx.propertyId,
                tx.tenantId,
                tx.paymentMethod,
                int(bool(tx.isReimbursable)),
                tx.attachmentUrl,
                int(bool(tx.isPaid)),
                id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError("Transaction not found")
        assert self.conn is not None
        self.conn.commit()
        return tx

    def delete_transaction(self, id: str) -> None:
        cur = self._cursor()
        cur.execute("DELETE FROM transactions WHERE id=?", (id,))
        assert self.conn is not None
        self.conn.commit()

    # --- Maintenance ---
    def list_maintenance(self, **filters) -> List[MaintenanceRequest]:
        cur = self._cursor()
        q = "SELECT * FROM maintenance"
        clauses = []
        params: List[Any] = []
        for key in ("status", "propertyId", "tenantId"):
            if key in filters and filters[key] is not None:
                clauses.append(f"{key} = ?")
                params.append(filters[key])
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [MaintenanceRequest(**self._row_to_dict(r)) for r in rows]

    def create_maintenance(self, req: MaintenanceRequest) -> MaintenanceRequest:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO maintenance (id,propertyId,tenantId,title,description,priority,status,dateReported) VALUES (?,?,?,?,?,?,?,?)",
            (
                req.id,
                req.propertyId,
                req.tenantId,
                req.title,
                req.description,
                req.priority,
                req.status,
                req.dateReported,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return req

    def update_maintenance(
        self, id: str, req: MaintenanceRequest
    ) -> MaintenanceRequest:
        cur = self._cursor()
        cur.execute(
            "UPDATE maintenance SET propertyId=?,tenantId=?,title=?,description=?,priority=?,status=?,dateReported=? WHERE id=?",
            (
                req.propertyId,
                req.tenantId,
                req.title,
                req.description,
                req.priority,
                req.status,
                req.dateReported,
                id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError("Maintenance request not found")
        assert self.conn is not None
        self.conn.commit()
        return req

    def delete_maintenance(self, id: str) -> None:
        cur = self._cursor()
        cur.execute("DELETE FROM maintenance WHERE id=?", (id,))
        assert self.conn is not None
        self.conn.commit()

    # --- Alerts ---
    def list_alerts(self) -> List[Alert]:
        cur = self._cursor()
        rows = cur.execute("SELECT * FROM alerts").fetchall()
        return [Alert(**self._row_to_dict(r)) for r in rows]

    # --- Settings ---
    def save_settings(self, s: LandlordSettings) -> LandlordSettings:
        cur = self._cursor()
        cur.execute(
            "INSERT OR REPLACE INTO settings (id,displayName,email,phone,companyName,currency,language) VALUES (1,?,?,?,?,?,?)",
            (s.displayName, s.email, s.phone, s.companyName, s.currency, s.language),
        )
        assert self.conn is not None
        self.conn.commit()
        return s
