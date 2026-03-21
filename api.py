"""
PropFlow FastAPI Backend - Multi-Tenant Property Management API

Architecture:
- api.py: FastAPI routes (request handling, auth, validation)
- db.py: Database abstraction layer (SQLModel ORM operations)
- database.py: Session management and engine setup
- auth.py: Authentication and authorization

All endpoints enforce project isolation via the database layer.
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from typing import List, Optional

# Import models
from PropFlow.models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    Alert,
    LandlordSettings,
)

# Import auth and database
from auth import get_current_project, get_current_user
from database import get_session, create_db_and_tables
from db import SQLModelDatabase

app = FastAPI(
    title="PropFlow API",
    description="Multi-tenant property management backend",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database instance
db = SQLModelDatabase()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.get("/health")
def health():
    return {"status": "ok"}


# ===== PROPERTIES =====


@app.get("/properties", response_model=List[Property])
def list_properties(
    project_id: str = Depends(get_current_project),
    type: Optional[str] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return db.list_properties(session, project_id, type=type, status=status)


@app.post("/properties", response_model=Property)
def create_property(
    p: Property,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    p.projectId = project_id
    return db.create_property(session, p)


@app.put("/properties/{id}", response_model=Property)
def update_property(
    id: str,
    p: Property,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        return db.update_property(session, id, p, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")


@app.delete("/properties/{id}", status_code=204)
def delete_property(
    id: str,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        db.delete_property(session, id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")


# ===== TENANTS =====


@app.get("/tenants", response_model=List[Tenant])
def list_tenants(
    project_id: str = Depends(get_current_project),
    propertyId: Optional[str] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return db.list_tenants(session, project_id, propertyId=propertyId, status=status)


@app.post("/tenants", response_model=Tenant)
def create_tenant(
    t: Tenant,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    t.projectId = project_id
    return db.create_tenant(session, t)


@app.put("/tenants/{id}", response_model=Tenant)
def update_tenant(
    id: str,
    t: Tenant,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        return db.update_tenant(session, id, t, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tenant not found")


@app.delete("/tenants/{id}", status_code=204)
def delete_tenant(
    id: str,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        db.delete_tenant(session, id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tenant not found")


# ===== TRANSACTIONS =====


@app.get("/transactions", response_model=List[Transaction])
def list_transactions(
    project_id: str = Depends(get_current_project),
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    type: Optional[str] = None,
    propertyId: Optional[str] = None,
    tenantId: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return db.list_transactions(
        session,
        project_id,
        startDate=startDate,
        endDate=endDate,
        type=type,
        propertyId=propertyId,
        tenantId=tenantId,
    )


@app.post("/transactions", response_model=Transaction)
def create_transaction(
    tx: Transaction,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    tx.projectId = project_id
    return db.create_transaction(session, tx)


@app.put("/transactions/{id}", response_model=Transaction)
def update_transaction(
    id: str,
    tx: Transaction,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        return db.update_transaction(session, id, tx, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Transaction not found")


@app.delete("/transactions/{id}", status_code=204)
def delete_transaction(
    id: str,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        db.delete_transaction(session, id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Transaction not found")


# ===== MAINTENANCE =====


@app.get("/maintenance", response_model=List[MaintenanceRequest])
def list_maintenance(
    project_id: str = Depends(get_current_project),
    status: Optional[str] = None,
    propertyId: Optional[str] = None,
    tenantId: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return db.list_maintenance(
        session,
        project_id,
        status=status,
        propertyId=propertyId,
        tenantId=tenantId,
    )


@app.post("/maintenance", response_model=MaintenanceRequest)
def create_maintenance(
    req: MaintenanceRequest,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    req.projectId = project_id
    return db.create_maintenance(session, req)


@app.put("/maintenance/{id}", response_model=MaintenanceRequest)
def update_maintenance(
    id: str,
    req: MaintenanceRequest,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        return db.update_maintenance(session, id, req, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Maintenance request not found")


@app.delete("/maintenance/{id}", status_code=204)
def delete_maintenance(
    id: str,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        db.delete_maintenance(session, id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Maintenance request not found")


# ===== ALERTS =====


@app.get("/alerts", response_model=List[Alert])
def list_alerts(
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return db.list_alerts(session, project_id)


@app.post("/alerts", response_model=Alert)
def create_alert(
    alert: Alert,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    alert.projectId = project_id
    return db.create_alert(session, alert)


@app.delete("/alerts/{id}", status_code=204)
def delete_alert(
    id: str,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        db.delete_alert(session, id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Alert not found")


# ===== SETTINGS =====


@app.get("/settings", response_model=LandlordSettings)
def get_settings(
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    settings = db.get_settings(session, project_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    return settings


@app.post("/settings", response_model=LandlordSettings)
def save_settings(
    s: LandlordSettings,
    project_id: str = Depends(get_current_project),
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    s.projectId = project_id
    return db.save_settings(session, s)


def main():
    import uvicorn
    import threading

    reload_flag = threading.current_thread() is threading.main_thread()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=reload_flag)


if __name__ == "__main__":
    main()
