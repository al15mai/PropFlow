import sqlite3
from sqlite3 import Connection, Cursor
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

import json

from models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    Alert,
    LandlordSettings,
    Document,
    InvoiceTemplate,
    User,
    Project,
    Invite,
)


class DatabaseInterface(ABC):
    @abstractmethod
    def initialize(self) -> None:
        pass

    # Properties
    @abstractmethod
    def list_properties(
        self,
        type: Optional[str] = None,
        status: Optional[str] = None,
        projectId: Optional[str] = None,
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
        self,
        propertyId: Optional[str] = None,
        status: Optional[str] = None,
        projectId: Optional[str] = None,
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
            # WAL: readers don't block the writer and vice-versa — a cheap
            # concurrency win now that several code paths touch the DB (task C6).
            # Persists on the DB file; harmless for the temp-file test DBs.
            self.conn.execute("PRAGMA journal_mode=WAL")

    def _cursor(self) -> Cursor:
        """Return a DB cursor ensuring the connection is initialized.

        This avoids static type checkers warning about `conn` possibly being None.
        """
        self._connect()
        assert self.conn is not None
        return self.conn.cursor()

    def initialize(self) -> None:
        cur = self._cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                id TEXT PRIMARY KEY,
                address TEXT,
                unitNumber TEXT,
                rooms INTEGER,
                rentAmount REAL,
                currency TEXT,
                status TEXT,
                type TEXT,
                image TEXT,
                fxRate REAL,
                projectId TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                propertyId TEXT,
                name TEXT,
                email TEXT,
                phone TEXT,
                leaseStart TEXT,
                leaseEnd TEXT,
                deposit REAL,
                status TEXT,
                rentDueDay INTEGER,
                projectId TEXT
            )""")
        cur.execute("""
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
                isPaid INTEGER,
                currency TEXT,
                fxRate REAL,
                amountBase REAL,
                maintenanceId TEXT,
                projectId TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS maintenance (
                id TEXT PRIMARY KEY,
                propertyId TEXT,
                tenantId TEXT,
                title TEXT,
                description TEXT,
                priority TEXT,
                status TEXT,
                dateReported TEXT,
                projectId TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                type TEXT,
                message TEXT,
                severity TEXT,
                date TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                displayName TEXT,
                email TEXT,
                phone TEXT,
                companyName TEXT,
                currency TEXT,
                language TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                transactionId TEXT,
                kind TEXT,
                filename TEXT,
                mime TEXT,
                size INTEGER,
                storage TEXT,
                path TEXT,
                url TEXT,
                sha256 TEXT,
                note TEXT,
                createdAt TEXT
            )""")
        # Per-vendor invoice-parsing rules authored in the app (task E7).
        # `spec` is JSON: {vendor, match:[phrase], category?, subcategory?,
        #  fields:{name:{after,kind}}}. Migration 008 adds this to the live DB.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_templates (
                id TEXT PRIMARY KEY,
                vendor TEXT,
                spec TEXT,
                source TEXT,
                projectId TEXT,
                createdAt TEXT
            )""")
        # Auth / multi-tenant (task D1). Migration 009 adds these to the live DB
        # and seeds the landlord user + their project.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                name TEXT,
                avatar TEXT,
                passwordHash TEXT,
                createdAt TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT,
                ownerId TEXT,
                currency TEXT,
                createdAt TEXT
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS project_members (
                projectId TEXT,
                userId TEXT,
                role TEXT,
                PRIMARY KEY (projectId, userId)
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id TEXT PRIMARY KEY,
                email TEXT,
                name TEXT,
                projectId TEXT,
                role TEXT,
                tokenHash TEXT,
                createdAt TEXT,
                acceptedAt TEXT
            )""")
        assert self.conn is not None
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    @staticmethod
    def _project_filter(project_id: Optional[str]) -> tuple:
        """Lenient project scoping (task D4b): a NULL-project row is 'legacy / shared'
        and shows in every workspace; a row with a projectId shows only in that one.
        No projectId asked for -> no clause (returns everything)."""
        if not project_id:
            return "", []
        return "(projectId IS NULL OR projectId = ?)", [project_id]

    # --- Properties ---
    def list_properties(
        self,
        type: Optional[str] = None,
        status: Optional[str] = None,
        projectId: Optional[str] = None,
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
        proj_clause, proj_params = self._project_filter(projectId)
        if proj_clause:
            clauses.append(proj_clause)
            params.extend(proj_params)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Property(**self._row_to_dict(r)) for r in rows]

    def get_property(self, id: str) -> Optional[Property]:
        row = self._cursor().execute("SELECT * FROM properties WHERE id = ?", (id,)).fetchone()
        return Property(**self._row_to_dict(row)) if row else None

    def create_property(self, p: Property) -> Property:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO properties (id,address,unitNumber,rooms,rentAmount,currency,status,type,image,fxRate,projectId) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                p.fxRate,
                p.projectId,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return p

    def update_property(self, id: str, p: Property) -> Property:
        cur = self._cursor()
        cur.execute(
            "UPDATE properties SET address=?,unitNumber=?,rooms=?,rentAmount=?,currency=?,status=?,type=?,image=?,fxRate=?,projectId=COALESCE(?,projectId) WHERE id=?",
            (
                p.address,
                p.unitNumber,
                p.rooms,
                p.rentAmount,
                p.currency,
                p.status,
                p.type,
                p.image,
                p.fxRate,
                p.projectId,
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
        self,
        propertyId: Optional[str] = None,
        status: Optional[str] = None,
        projectId: Optional[str] = None,
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
        proj_clause, proj_params = self._project_filter(projectId)
        if proj_clause:
            clauses.append(proj_clause)
            params.extend(proj_params)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Tenant(**self._row_to_dict(r)) for r in rows]

    def get_tenant(self, id: str) -> Optional[Tenant]:
        row = self._cursor().execute("SELECT * FROM tenants WHERE id = ?", (id,)).fetchone()
        return Tenant(**self._row_to_dict(row)) if row else None

    def create_tenant(self, t: Tenant) -> Tenant:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO tenants (id,propertyId,name,email,phone,leaseStart,leaseEnd,deposit,status,rentDueDay,projectId) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                t.rentDueDay,
                t.projectId,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return t

    def update_tenant(self, id: str, t: Tenant) -> Tenant:
        cur = self._cursor()
        cur.execute(
            "UPDATE tenants SET propertyId=?,name=?,email=?,phone=?,leaseStart=?,leaseEnd=?,deposit=?,status=?,rentDueDay=?,projectId=COALESCE(?,projectId) WHERE id=?",
            (
                t.propertyId,
                t.name,
                t.email,
                t.phone,
                t.leaseStart,
                t.leaseEnd,
                t.deposit,
                t.status,
                t.rentDueDay,
                t.projectId,
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
        for key in ("startDate", "endDate", "type", "propertyId", "tenantId", "maintenanceId"):
            if key in filters and filters[key] is not None:
                if key == "startDate":
                    clauses.append("date >= ?")
                elif key == "endDate":
                    clauses.append("date <= ?")
                else:
                    clauses.append(f"{key} = ?")
                params.append(filters[key])
        proj_clause, proj_params = self._project_filter(filters.get("projectId"))
        if proj_clause:
            clauses.append(proj_clause)
            params.extend(proj_params)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [Transaction(**self._row_to_dict(r)) for r in rows]

    def _resolve_property_id(self, tx: Transaction) -> Optional[str]:
        """A tenant-linked transaction belongs to that tenant's property. Fill it in
        when the client didn't, so per-property views/filters stay correct
        (see migration 001 / tasks A2, A3)."""
        if tx.propertyId or not tx.tenantId:
            return tx.propertyId
        cur = self._cursor()
        row = cur.execute(
            "SELECT propertyId FROM tenants WHERE id = ?", (tx.tenantId,)
        ).fetchone()
        return row[0] if row and row[0] else tx.propertyId

    @staticmethod
    def _currency_fields(tx: Transaction) -> tuple:
        """Normalize the multi-currency triple (task A4): fxRate defaults to 1,
        amountBase is derived from amount * fxRate when the client didn't send it.
        `currency` is stored as given (None == base currency)."""
        fx = tx.fxRate if tx.fxRate else 1.0
        base = tx.amountBase if tx.amountBase is not None else round((tx.amount or 0) * fx, 2)
        return tx.currency, fx, base

    def get_transaction(self, id: str) -> Optional[Transaction]:
        row = self._cursor().execute("SELECT * FROM transactions WHERE id = ?", (id,)).fetchone()
        return Transaction(**self._row_to_dict(row)) if row else None

    def create_transaction(self, tx: Transaction) -> Transaction:
        cur = self._cursor()
        tx.propertyId = self._resolve_property_id(tx)
        currency, fx_rate, amount_base = self._currency_fields(tx)
        tx.fxRate, tx.amountBase = fx_rate, amount_base
        cur.execute(
            "INSERT INTO transactions (id,date,amount,type,category,subcategory,description,propertyId,tenantId,paymentMethod,isReimbursable,isPaid,currency,fxRate,amountBase,maintenanceId,projectId) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tx.id,
                tx.date,
                tx.amount,
                tx.type,
                tx.category,
                tx.subcategory,
                tx.description or "",
                tx.propertyId,
                tx.tenantId,
                tx.paymentMethod,
                int(bool(tx.isReimbursable)),
                int(bool(tx.isPaid)),
                currency,
                fx_rate,
                amount_base,
                tx.maintenanceId,
                tx.projectId,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return tx

    def update_transaction(self, id: str, tx: Transaction) -> Transaction:
        cur = self._cursor()
        tx.propertyId = self._resolve_property_id(tx)
        currency, fx_rate, amount_base = self._currency_fields(tx)
        tx.fxRate, tx.amountBase = fx_rate, amount_base
        cur.execute(
            "UPDATE transactions SET date=?,amount=?,type=?,category=?,subcategory=?,description=?,propertyId=?,tenantId=?,paymentMethod=?,isReimbursable=?,isPaid=?,currency=?,fxRate=?,amountBase=?,maintenanceId=?,projectId=COALESCE(?,projectId) WHERE id=?",
            (
                tx.date,
                tx.amount,
                tx.type,
                tx.category,
                tx.subcategory,
                tx.description or "",
                tx.propertyId,
                tx.tenantId,
                tx.paymentMethod,
                int(bool(tx.isReimbursable)),
                int(bool(tx.isPaid)),
                currency,
                fx_rate,
                amount_base,
                tx.maintenanceId,
                tx.projectId,
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
        proj_clause, proj_params = self._project_filter(filters.get("projectId"))
        if proj_clause:
            clauses.append(proj_clause)
            params.extend(proj_params)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = cur.execute(q, params).fetchall()
        return [MaintenanceRequest(**self._row_to_dict(r)) for r in rows]

    def get_maintenance(self, id: str) -> Optional[MaintenanceRequest]:
        row = self._cursor().execute("SELECT * FROM maintenance WHERE id = ?", (id,)).fetchone()
        return MaintenanceRequest(**self._row_to_dict(row)) if row else None

    def create_maintenance(self, req: MaintenanceRequest) -> MaintenanceRequest:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO maintenance (id,propertyId,tenantId,title,description,priority,status,dateReported,projectId) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                req.id,
                req.propertyId,
                req.tenantId,
                req.title,
                req.description,
                req.priority,
                req.status,
                req.dateReported,
                req.projectId,
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
            "UPDATE maintenance SET propertyId=?,tenantId=?,title=?,description=?,priority=?,status=?,dateReported=?,projectId=COALESCE(?,projectId) WHERE id=?",
            (
                req.propertyId,
                req.tenantId,
                req.title,
                req.description,
                req.priority,
                req.status,
                req.dateReported,
                req.projectId,
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

    # --- Documents (task E8) ---
    _DOC_COLS = (
        "id,transactionId,kind,filename,mime,size,storage,path,url,sha256,note,createdAt"
    )

    def create_document(self, d: Document) -> Document:
        cur = self._cursor()
        cur.execute(
            f"INSERT INTO documents ({self._DOC_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.id,
                d.transactionId,
                d.kind,
                d.filename,
                d.mime,
                d.size,
                d.storage,
                d.path,
                d.url,
                d.sha256,
                d.note or "",
                d.createdAt,
            ),
        )
        assert self.conn is not None
        self.conn.commit()
        return d

    def get_document(self, id: str) -> Optional[Document]:
        cur = self._cursor()
        row = cur.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()
        return Document(**self._row_to_dict(row)) if row else None

    def list_documents(
        self,
        transactionId: Optional[str] = None,
        tenantId: Optional[str] = None,
        pending: Optional[bool] = None,
    ) -> List[Document]:
        cur = self._cursor()
        clauses: List[str] = []
        params: List[Any] = []
        if transactionId is not None:
            clauses.append("d.transactionId = ?")
            params.append(transactionId)
        if tenantId is not None:
            # a tenant sees a document through their transactions
            clauses.append(
                "d.transactionId IN (SELECT id FROM transactions WHERE tenantId = ?)"
            )
            params.append(tenantId)
        if pending is True:
            clauses.append("d.transactionId IS NULL")
        elif pending is False:
            clauses.append("d.transactionId IS NOT NULL")
        q = "SELECT d.* FROM documents d"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY d.createdAt DESC"
        rows = cur.execute(q, params).fetchall()
        return [Document(**self._row_to_dict(r)) for r in rows]

    def update_document(self, id: str, **fields) -> Document:
        allowed = {"transactionId", "kind", "note"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            doc = self.get_document(id)
            if doc is None:
                raise KeyError("Document not found")
            return doc
        cur = self._cursor()
        cur.execute(
            f"UPDATE documents SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            (*sets.values(), id),
        )
        if cur.rowcount == 0:
            raise KeyError("Document not found")
        assert self.conn is not None
        self.conn.commit()
        got = self.get_document(id)
        assert got is not None
        return got

    def delete_document(self, id: str) -> Optional[Document]:
        """Delete the row, returning it so the caller can unlink the file."""
        doc = self.get_document(id)
        if doc is None:
            return None
        cur = self._cursor()
        cur.execute("DELETE FROM documents WHERE id = ?", (id,))
        assert self.conn is not None
        self.conn.commit()
        return doc

    # --- Invoice templates (task E7) ---
    @staticmethod
    def _row_to_template(row: sqlite3.Row) -> InvoiceTemplate:
        d = {k: row[k] for k in row.keys()}
        d["spec"] = json.loads(d["spec"]) if d.get("spec") else {}
        return InvoiceTemplate(**d)

    def create_invoice_template(self, t: InvoiceTemplate) -> InvoiceTemplate:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO invoice_templates (id,vendor,spec,source,projectId,createdAt) "
            "VALUES (?,?,?,?,?,?)",
            (t.id, t.vendor, json.dumps(t.spec), t.source, t.projectId, t.createdAt),
        )
        assert self.conn is not None
        self.conn.commit()
        return t

    def get_invoice_template(self, id: str) -> Optional[InvoiceTemplate]:
        row = self._cursor().execute(
            "SELECT * FROM invoice_templates WHERE id = ?", (id,)
        ).fetchone()
        return self._row_to_template(row) if row else None

    def list_invoice_templates(self, projectId: Optional[str] = None) -> List[InvoiceTemplate]:
        cur = self._cursor()
        where, params = self._project_filter(projectId)
        q = "SELECT * FROM invoice_templates"
        if where:
            q += " WHERE " + where
        q += " ORDER BY createdAt DESC"
        return [self._row_to_template(r) for r in cur.execute(q, params).fetchall()]

    def update_invoice_template(self, id: str, **fields) -> InvoiceTemplate:
        allowed = {"vendor", "spec", "source"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            got = self.get_invoice_template(id)
            if got is None:
                raise KeyError("Invoice template not found")
            return got
        if "spec" in sets:
            sets["spec"] = json.dumps(sets["spec"])
        cur = self._cursor()
        cur.execute(
            f"UPDATE invoice_templates SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            (*sets.values(), id),
        )
        if cur.rowcount == 0:
            raise KeyError("Invoice template not found")
        assert self.conn is not None
        self.conn.commit()
        got = self.get_invoice_template(id)
        assert got is not None
        return got

    def delete_invoice_template(self, id: str) -> Optional[InvoiceTemplate]:
        got = self.get_invoice_template(id)
        if got is None:
            return None
        cur = self._cursor()
        cur.execute("DELETE FROM invoice_templates WHERE id = ?", (id,))
        assert self.conn is not None
        self.conn.commit()
        return got

    # --- Users (task D1) ---

    def create_user(
        self, id: str, email: str, name: str, password_hash: str,
        avatar: Optional[str], created_at: str,
    ) -> User:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO users (id,email,name,avatar,passwordHash,createdAt) VALUES (?,?,?,?,?,?)",
            (id, email.lower().strip(), name, avatar, password_hash, created_at),
        )
        assert self.conn is not None
        self.conn.commit()
        got = self.get_user(id)
        assert got is not None
        return got

    def get_user(self, id: str) -> Optional[User]:
        row = self._cursor().execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()
        return User(**self._row_to_dict(row)) if row else None

    def get_user_by_email(self, email: str) -> Optional[User]:
        row = self._cursor().execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return User(**self._row_to_dict(row)) if row else None

    def get_user_password_hash(self, email: str) -> Optional[tuple[str, str]]:
        """(user_id, passwordHash) for a login check, or None. Kept off the `User`
        model so a hash can never leak through a serialized response."""
        row = self._cursor().execute(
            "SELECT id, passwordHash FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return (row["id"], row["passwordHash"]) if row else None

    def set_user_password(self, user_id: str, password_hash: str) -> None:
        cur = self._cursor()
        cur.execute("UPDATE users SET passwordHash = ? WHERE id = ?", (password_hash, user_id))
        assert self.conn is not None
        self.conn.commit()

    def count_users(self) -> int:
        return self._cursor().execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # --- Projects (task D1) ---

    def _project_with_members(self, row: sqlite3.Row) -> Project:
        d = self._row_to_dict(row)
        members = self._cursor().execute(
            "SELECT userId FROM project_members WHERE projectId = ?", (d["id"],)
        ).fetchall()
        d["members"] = [m["userId"] for m in members]
        return Project(**d)

    def create_project(
        self, id: str, name: str, owner_id: str, currency: str, created_at: str,
    ) -> Project:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO projects (id,name,ownerId,currency,createdAt) VALUES (?,?,?,?,?)",
            (id, name, owner_id, currency, created_at),
        )
        cur.execute(
            "INSERT OR IGNORE INTO project_members (projectId,userId,role) VALUES (?,?,?)",
            (id, owner_id, "owner"),
        )
        assert self.conn is not None
        self.conn.commit()
        got = self.get_project(id)
        assert got is not None
        return got

    def get_project(self, id: str) -> Optional[Project]:
        row = self._cursor().execute("SELECT * FROM projects WHERE id = ?", (id,)).fetchone()
        return self._project_with_members(row) if row else None

    def list_projects_for_user(self, user_id: str) -> List[Project]:
        rows = self._cursor().execute(
            "SELECT p.* FROM projects p "
            "JOIN project_members m ON m.projectId = p.id "
            "WHERE m.userId = ? ORDER BY p.createdAt",
            (user_id,),
        ).fetchall()
        return [self._project_with_members(r) for r in rows]

    def is_project_member(self, project_id: str, user_id: str) -> bool:
        return self._cursor().execute(
            "SELECT 1 FROM project_members WHERE projectId = ? AND userId = ?",
            (project_id, user_id),
        ).fetchone() is not None

    def list_project_members(self, project_id: str) -> List[Dict[str, Any]]:
        """[{id, name, email, role}] for the Team screen (task D1d)."""
        rows = self._cursor().execute(
            "SELECT u.id, u.name, u.email, m.role "
            "FROM project_members m JOIN users u ON u.id = m.userId "
            "WHERE m.projectId = ? "
            "ORDER BY (m.role = 'owner') DESC, u.name",
            (project_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"]} for r in rows]

    def user_owns_any_project(self, user_id: str) -> bool:
        """True if this user is the 'owner' of at least one project — the proxy
        for 'is the landlord' used by owner-gated routes (task D1c)."""
        return self._cursor().execute(
            "SELECT 1 FROM project_members WHERE userId = ? AND role = 'owner' LIMIT 1",
            (user_id,),
        ).fetchone() is not None

    def add_project_member(self, project_id: str, user_id: str, role: str = "member") -> None:
        cur = self._cursor()
        cur.execute(
            "INSERT OR REPLACE INTO project_members (projectId,userId,role) VALUES (?,?,?)",
            (project_id, user_id, role),
        )
        assert self.conn is not None
        self.conn.commit()

    def count_projects(self) -> int:
        return self._cursor().execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    # --- Invites (task D1) ---

    def create_invite(
        self, id: str, email: str, name: Optional[str], project_id: str,
        role: str, token_hash: str, created_at: str,
    ) -> Invite:
        cur = self._cursor()
        cur.execute(
            "INSERT INTO invites (id,email,name,projectId,role,tokenHash,createdAt,acceptedAt) "
            "VALUES (?,?,?,?,?,?,?,NULL)",
            (id, email.lower().strip(), name, project_id, role, token_hash, created_at),
        )
        assert self.conn is not None
        self.conn.commit()
        got = self.get_invite(id)
        assert got is not None
        return got

    def get_invite(self, id: str) -> Optional[Invite]:
        row = self._cursor().execute("SELECT * FROM invites WHERE id = ?", (id,)).fetchone()
        return Invite(**self._row_to_dict(row)) if row else None

    def get_invite_by_token_hash(self, token_hash: str) -> Optional[Invite]:
        row = self._cursor().execute(
            "SELECT * FROM invites WHERE tokenHash = ?", (token_hash,)
        ).fetchone()
        return Invite(**self._row_to_dict(row)) if row else None

    def list_invites(self, project_id: str) -> List[Invite]:
        rows = self._cursor().execute(
            "SELECT * FROM invites WHERE projectId = ? ORDER BY createdAt DESC", (project_id,)
        ).fetchall()
        return [Invite(**self._row_to_dict(r)) for r in rows]

    def mark_invite_accepted(self, invite_id: str, accepted_at: str) -> None:
        cur = self._cursor()
        cur.execute("UPDATE invites SET acceptedAt = ? WHERE id = ?", (accepted_at, invite_id))
        assert self.conn is not None
        self.conn.commit()

    def delete_invite(self, id: str) -> None:
        cur = self._cursor()
        cur.execute("DELETE FROM invites WHERE id = ?", (id,))
        assert self.conn is not None
        self.conn.commit()
