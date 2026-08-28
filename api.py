import hashlib
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Optional
from datetime import datetime

app = FastAPI()

# CORS: in production the frontend is served by THIS app (same origin — task D6),
# so only the local dev servers need listing. (`allow_origins=["*"]` together with
# credentials is rejected by browsers anyway.) `$PROPFLOW_CORS_ORIGINS` (comma-sep)
# overrides, e.g. once there's a public HTTPS origin.
_DEV_ORIGINS = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5173", "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o for o in os.environ.get("PROPFLOW_CORS_ORIGINS", ",".join(_DEV_ORIGINS)).split(",") if o
    ],
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
    InvoiceTemplate,
    InvoiceExtraction,
)

from db import SQLiteDatabase
from system_update import get_git_status

# Uploaded document files live OUTSIDE the repo tree (task E8b decision) so a
# `git clean` / redeploy never wipes them and backups can cover them alongside
# data.db. Default: ~/propflow-data/uploads. Production MUST set $PROPFLOW_UPLOADS
# (the test suite points it at a tmp dir). Resolved per-call so tests get an
# isolated dir without monkeypatching.
def _uploads_dir() -> Path:
    d = Path(
        os.environ.get("PROPFLOW_UPLOADS")
        or (Path.home() / "propflow-data" / "uploads")
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


# --- Invoice OCR / quick cost entry (task E7) -------------------------------
#
# Extraction runs server-side (E7 decision). PDF-first: pull the text layer,
# redact PII (mandatory before this text could ever reach an LLM), then match a
# per-vendor template. Image / link invoices fall through to needs-review until
# the E5 model fallback lands. Nothing is written — the frontend confirms the
# fields and creates the transaction itself.

def _split_names(raw: Optional[str]) -> list:
    return [p.strip() for p in (raw or "").replace(";", ",").split(",") if p.strip()]


def _load_project_templates(project_id: Optional[str]):
    from invoice.templates import TemplateSpecError, template_from_spec

    out = []
    for row in db.list_invoice_templates(project_id):
        try:
            out.append(template_from_spec(row.spec, source=row.source))
        except TemplateSpecError:
            continue  # a broken saved template shouldn't break extraction
    return out


def _extract_from_text(text: str, *, names, places, project_id) -> InvoiceExtraction:
    from invoice import extract, redact

    red = redact(text, names=names, extra=[re.escape(p) for p in places])
    res = extract(red.text, templates=_load_project_templates(project_id))
    return InvoiceExtraction(
        parsed=res.to_parsed_invoice(),
        needsReview=sorted(res.needs_review),
        templateVendor=res.template,
        dueDate=res.due_date,
        source=res.source,
    )


@app.post("/invoices/extract", response_model=InvoiceExtraction)
async def extract_invoice(
    file: Optional[UploadFile] = File(None),
    documentId: Optional[str] = Form(None),
    names: Optional[str] = Form(None),   # tenant/owner names to scrub, comma-sep
    places: Optional[str] = Form(None),  # property city/county to scrub, comma-sep
    projectId: Optional[str] = Form(None),
):
    names_list = _split_names(names)
    places_list = _split_names(places)

    data: Optional[bytes] = None
    is_pdf = False
    if file is not None:
        data = await file.read()
        is_pdf = (file.content_type == "application/pdf") or data[:5] == b"%PDF-"
    elif documentId:
        doc = db.get_document(documentId)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.storage != "file" or not doc.path:
            # a link document — fetching it is the E5 fallback's job
            return InvoiceExtraction(
                parsed={"vendor": "", "amount": 0, "date": "", "category": "Utilities",
                        "subcategory": None, "description": ""},
                needsReview=["vendor", "amount", "date"], source="manual",
            )
        fp = _uploads_dir() / doc.path
        if not fp.exists():
            raise HTTPException(status_code=410, detail="File missing on disk")
        data = fp.read_bytes()
        is_pdf = (doc.mime == "application/pdf") or data[:5] == b"%PDF-"
    else:
        raise HTTPException(status_code=422, detail="provide a file or a documentId")

    if not is_pdf:
        # image invoice — needs the E5 model path; return an empty shell to fill in
        return InvoiceExtraction(
            parsed={"vendor": "", "amount": 0, "date": "", "category": "Utilities",
                    "subcategory": None, "description": ""},
            needsReview=["vendor", "amount", "date"], source="manual",
        )

    from invoice import pdf_to_text

    try:
        text = pdf_to_text(data)
    except Exception:
        raise HTTPException(status_code=422, detail="could not read the PDF")

    return _extract_from_text(text, names=names_list, places=places_list, project_id=projectId)


@app.get("/invoice-templates", response_model=List[InvoiceTemplate])
def list_invoice_templates(projectId: Optional[str] = None):
    return db.list_invoice_templates(projectId)


@app.post("/invoice-templates", response_model=InvoiceTemplate, status_code=201)
def create_invoice_template(t: InvoiceTemplate):
    from invoice.templates import TemplateSpecError, template_from_spec

    try:
        template_from_spec(t.spec, source=t.source)  # validate before storing
    except TemplateSpecError as e:
        raise HTTPException(status_code=422, detail=f"bad template: {e}")
    if not t.id:
        t.id = uuid.uuid4().hex
    if not t.createdAt:
        t.createdAt = now_iso()
    return db.create_invoice_template(t)


@app.put("/invoice-templates/{id}", response_model=InvoiceTemplate)
def update_invoice_template(id: str, patch: dict):
    from invoice.templates import TemplateSpecError, template_from_spec

    if "spec" in patch:
        try:
            template_from_spec(patch["spec"], source=patch.get("source", "user"))
        except TemplateSpecError as e:
            raise HTTPException(status_code=422, detail=f"bad template: {e}")
    try:
        return db.update_invoice_template(id, **patch)
    except KeyError:
        raise HTTPException(status_code=404, detail="Invoice template not found")


@app.delete("/invoice-templates/{id}", status_code=204)
def delete_invoice_template(id: str):
    db.delete_invoice_template(id)
    return


# --- Static frontend bundle (task D6) ---------------------------------------
# On the VPS the built `dist/` is served by this app (one origin, no Node
# process). Mounted LAST so it never shadows an API route. In dev there's no
# build dir, so this is a no-op and `npm run dev` serves the UI itself.
_DIST_DIR = Path(
    os.environ.get("PROPFLOW_DIST") or (Path(__file__).resolve().parent.parent / "dist")
)
if _DIST_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    # html=True → serves index.html at "/" (the app has no server-side routes,
    # view state is client-side).
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="frontend")


def main():
    import uvicorn
    import threading

    # Only enable reload when running in the main thread —
    # uvicorn's reloader uses signals which are not allowed in other threads.
    reload_flag = threading.current_thread() is threading.main_thread()
    port = int(os.environ.get("PROPFLOW_API_PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=reload_flag)


if __name__ == "__main__":
    main()
