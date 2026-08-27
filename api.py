import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import List, Optional
from datetime import datetime

app = FastAPI()

# Allow CORS from frontend dev servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from models import (
    Property,
    Tenant,
    Transaction,
    MaintenanceRequest,
    Alert,
    LandlordSettings,
)

from db import SQLiteDatabase

# The DB path is anchored to this file, NOT the process cwd. There used to be a
# second, empty `data.db` at the repo root that got picked up whenever the server
# was started from the wrong directory (see task C5 / CLAUDE.md "Which database is
# real?"). `PROPFLOW_DB` overrides it — the test suite points it at a throwaway
# tmp file so importing this module never touches production data.
DB_PATH = os.environ.get("PROPFLOW_DB") or str(Path(__file__).resolve().parent / "data.db")

db = SQLiteDatabase(path=DB_PATH)
db.initialize()


def now_iso():
    return datetime.utcnow().isoformat()


# Health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}


# --- Properties ---
@app.get("/properties", response_model=List[Property])
def list_properties(type: Optional[str] = None, status: Optional[str] = None):
    return db.list_properties(type=type, status=status)


@app.post("/properties", response_model=Property)
def create_property(p: Property):
    db.create_property(p)
    return p


@app.put("/properties/{id}", response_model=Property)
def update_property(id: str, p: Property):
    try:
        db.update_property(id, p)
        return p
    except KeyError:
        raise HTTPException(status_code=404, detail="Property not found")


@app.delete("/properties/{id}", status_code=204)
def delete_property(id: str):
    db.delete_property(id)
    return


# --- Tenants ---
@app.get("/tenants", response_model=List[Tenant])
def list_tenants(propertyId: Optional[str] = None, status: Optional[str] = None):
    return db.list_tenants(propertyId=propertyId, status=status)


@app.post("/tenants", response_model=Tenant)
def create_tenant(t: Tenant):
    db.create_tenant(t)
    return t


@app.put("/tenants/{id}", response_model=Tenant)
def update_tenant(id: str, t: Tenant):
    try:
        db.update_tenant(id, t)
        return t
    except KeyError:
        raise HTTPException(status_code=404, detail="Tenant not found")


@app.delete("/tenants/{id}", status_code=204)
def delete_tenant(id: str):
    db.delete_tenant(id)
    return


# --- Transactions ---
@app.get("/transactions", response_model=List[Transaction])
def list_transactions(
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    type: Optional[str] = None,
    propertyId: Optional[str] = None,
    tenantId: Optional[str] = None,
):
    return db.list_transactions(
        startDate=startDate,
        endDate=endDate,
        type=type,
        propertyId=propertyId,
        tenantId=tenantId,
    )


@app.post("/transactions", response_model=Transaction)
def create_transaction(tx: Transaction):
    db.create_transaction(tx)
    return tx


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("Validation error for request:", request.method, request.url)
    print("Body:", await request.body())
    print("Errors:", exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body": exc.body,
        },
    )


@app.put("/transactions/{id}", response_model=Transaction)
def update_transaction(id: str, tx: Transaction):
    try:
        db.update_transaction(id, tx)
        return tx
    except KeyError:
        raise HTTPException(status_code=404, detail="Transaction not found")


@app.delete("/transactions/{id}", status_code=204)
def delete_transaction(id: str):
    db.delete_transaction(id)
    return


# --- Maintenance ---
@app.get("/maintenance", response_model=List[MaintenanceRequest])
def list_maintenance(
    status: Optional[str] = None,
    propertyId: Optional[str] = None,
    tenantId: Optional[str] = None,
):
    return db.list_maintenance(status=status, propertyId=propertyId, tenantId=tenantId)


@app.post("/maintenance", response_model=MaintenanceRequest)
def create_maintenance(req: MaintenanceRequest):
    db.create_maintenance(req)
    return req


@app.put("/maintenance/{id}", response_model=MaintenanceRequest)
def update_maintenance(id: str, req: MaintenanceRequest):
    try:
        db.update_maintenance(id, req)
        return req
    except KeyError:
        raise HTTPException(status_code=404, detail="Maintenance request not found")


@app.delete("/maintenance/{id}", status_code=204)
def delete_maintenance(id: str):
    db.delete_maintenance(id)
    return


# --- Alerts ---
@app.get("/alerts", response_model=List[Alert])
def list_alerts():
    return db.list_alerts()


# --- Settings ---
@app.post("/settings", response_model=LandlordSettings)
def save_settings(s: LandlordSettings):
    db.save_settings(s)
    return s


def main():
    import uvicorn
    import threading

    # Only enable reload when running in the main thread —
    # uvicorn's reloader uses signals which are not allowed in other threads.
    reload_flag = threading.current_thread() is threading.main_thread()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=reload_flag)


if __name__ == "__main__":
    main()
