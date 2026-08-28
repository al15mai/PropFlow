import hashlib
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
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
    Document,
)

from db import SQLiteDatabase
from system_update import get_git_status

# Uploaded document files live next to the DB (data is tiny). Anchored to this
# file, override with $PROPFLOW_UPLOADS (the test suite points it at a tmp dir).
# Resolved per-call so tests get an isolated dir without monkeypatching.
def _uploads_dir() -> Path:
    d = Path(
        os.environ.get("PROPFLOW_UPLOADS")
        or (Path(__file__).resolve().parent / "uploads")
    )
    d.mkdir(parents=True, exist_ok=True)
    return d

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


# Running git identity of this backend, for the Settings > Version card (task D5).
@app.get("/admin/version")
def admin_version():
    return get_git_status()


# --- Properties ---
@app.get("/properties", response_model=List[Property])
def list_properties(
    type: Optional[str] = None,
    status: Optional[str] = None,
    projectId: Optional[str] = None,
):
    return db.list_properties(type=type, status=status, projectId=projectId)


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
def list_tenants(
    propertyId: Optional[str] = None,
    status: Optional[str] = None,
    projectId: Optional[str] = None,
):
    return db.list_tenants(propertyId=propertyId, status=status, projectId=projectId)


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
    maintenanceId: Optional[str] = None,
    projectId: Optional[str] = None,
):
    return db.list_transactions(
        startDate=startDate,
        endDate=endDate,
        type=type,
        propertyId=propertyId,
        tenantId=tenantId,
        maintenanceId=maintenanceId,
        projectId=projectId,
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
    projectId: Optional[str] = None,
):
    return db.list_maintenance(
        status=status, propertyId=propertyId, tenantId=tenantId, projectId=projectId
    )


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


# --- Documents (task E8) ---
_EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _doc_response(doc: Document) -> dict:
    """What the client gets back — includes a ready-to-use fetch URL."""
    out = doc.model_dump()
    out["fileUrl"] = f"/documents/{doc.id}/file" if doc.storage == "file" else doc.url
    return out


@app.get("/documents")
def list_documents(
    transactionId: Optional[str] = None,
    tenantId: Optional[str] = None,
    pending: Optional[bool] = None,
):
    return [_doc_response(d) for d in db.list_documents(transactionId, tenantId, pending)]


@app.post("/documents", status_code=201)
async def create_document(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    transactionId: Optional[str] = Form(None),
    kind: str = Form("other"),
    note: str = Form(""),
    filename: Optional[str] = Form(None),
):
    if kind not in ("invoice", "receipt", "bill", "other"):
        kind = "other"
    doc_id = uuid.uuid4().hex
    created = now_iso()

    if file is not None:
        data = await file.read()
        sha = hashlib.sha256(data).hexdigest()
        mime = file.content_type or "application/octet-stream"
        orig = filename or file.filename or "document"
        ext = Path(orig).suffix or _EXT_BY_MIME.get(mime, "")
        rel = f"{doc_id}{ext}"
        (_uploads_dir() / rel).write_bytes(data)
        doc = Document(
            id=doc_id, transactionId=transactionId or None, kind=kind, filename=orig,
            mime=mime, size=len(data), storage="file", path=rel, sha256=sha,
            note=note, createdAt=created,
        )
    elif url:
        doc = Document(
            id=doc_id, transactionId=transactionId or None, kind=kind,
            filename=url.rsplit("/", 1)[-1] or "link", storage="link", url=url,
            note=note, createdAt=created,
        )
    else:
        raise HTTPException(status_code=422, detail="provide a file or a url")

    db.create_document(doc)
    return _doc_response(doc)


@app.get("/documents/{id}/file")
def get_document_file(id: str):
    doc = db.get_document(id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.storage != "file" or not doc.path:
        raise HTTPException(status_code=409, detail="This document is a link, not a stored file")
    fp = _uploads_dir() / doc.path
    if not fp.exists():
        raise HTTPException(status_code=410, detail="File missing on disk")
    return FileResponse(fp, media_type=doc.mime or "application/octet-stream", filename=doc.filename)


@app.put("/documents/{id}", response_model=Document)
def update_document(id: str, patch: dict):
    try:
        return db.update_document(id, **patch)
    except KeyError:
        raise HTTPException(status_code=404, detail="Document not found")


@app.delete("/documents/{id}", status_code=204)
def delete_document(id: str):
    doc = db.delete_document(id)
    if doc and doc.storage == "file" and doc.path:
        (_uploads_dir() / doc.path).unlink(missing_ok=True)
    return


def main():
    import uvicorn
    import threading

    # Only enable reload when running in the main thread —
    # uvicorn's reloader uses signals which are not allowed in other threads.
    reload_flag = threading.current_thread() is threading.main_thread()
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=reload_flag)


if __name__ == "__main__":
    main()
