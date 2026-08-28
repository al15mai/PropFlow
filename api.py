import hashlib
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Depends, Header
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
    User,
    Project,
    Invite,
    LoginRequest,
    CreateInviteRequest,
    AcceptInviteRequest,
    AuthResponse,
)

from db import SQLiteDatabase
from system_update import get_git_status
import auth

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


_REQUIRED_FIELDS = ("vendor", "amount", "date")


async def _invoice_bytes(file, document_id) -> tuple:
    """Resolve (bytes, is_pdf) from an uploaded file or a stored document id."""
    if file is not None:
        data = await file.read()
        return data, (file.content_type == "application/pdf") or data[:5] == b"%PDF-"
    if document_id:
        doc = db.get_document(document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.storage != "file" or not doc.path:
            raise HTTPException(status_code=409, detail="That document is a link, not a file")
        fp = _uploads_dir() / doc.path
        if not fp.exists():
            raise HTTPException(status_code=410, detail="File missing on disk")
        data = fp.read_bytes()
        return data, (doc.mime == "application/pdf") or data[:5] == b"%PDF-"
    raise HTTPException(status_code=422, detail="provide a file or a documentId")


def _merge_extraction(res, model_fields: dict, *, source: str) -> InvoiceExtraction:
    """Start from a template `ExtractionResult` (or None) and fill gaps from the
    model. `dueDate` maps to `dueDate`; everything else lands in `parsed`."""
    parsed = res.to_parsed_invoice() if res is not None else {
        "vendor": "", "amount": 0, "date": "", "category": "Utilities",
        "subcategory": None, "description": "",
    }
    due = res.due_date if res is not None else None
    used_model = False
    for k in ("vendor", "amount", "date", "category", "subcategory"):
        empty = not parsed.get(k) or (k == "amount" and not parsed.get("amount"))
        if empty and model_fields.get(k) not in (None, ""):
            parsed[k] = model_fields[k]
            used_model = True
    if not due and model_fields.get("dueDate"):
        due = model_fields["dueDate"]
        used_model = True
    if used_model and not parsed.get("description"):
        parsed["description"] = " — ".join(
            x for x in (parsed.get("vendor"), parsed.get("subcategory")) if x
        )
    needs = [f for f in _REQUIRED_FIELDS if not parsed.get(f)]
    return InvoiceExtraction(
        parsed=parsed, needsReview=needs, dueDate=due,
        templateVendor=(res.template if res is not None else None),
        source=("model" if used_model and res is None else
                "template+model" if used_model else
                (res.source if res is not None else source)),
    )


@app.post("/invoices/extract", response_model=InvoiceExtraction)
async def extract_invoice(
    file: Optional[UploadFile] = File(None),
    documentId: Optional[str] = Form(None),
    names: Optional[str] = Form(None),   # tenant/owner names to scrub, comma-sep
    places: Optional[str] = Form(None),  # property city/county to scrub, comma-sep
    projectId: Optional[str] = Form(None),
):
    from invoice import extract, pdf_to_text, redact
    from llm import feature_mode

    names_list, places_list = _split_names(names), _split_names(places)
    data, is_pdf = await _invoice_bytes(file, documentId)
    want_model = feature_mode("invoice") in ("browser", "auto")

    if not is_pdf:
        # image invoice: only the model can read it
        fields = _model_extract_invoice(image_png=data) if want_model else {}
        return _merge_extraction(None, fields, source="manual")

    try:
        raw = pdf_to_text(data)
    except Exception:
        raise HTTPException(status_code=422, detail="could not read the PDF")

    red = redact(raw, names=names_list, extra=[re.escape(p) for p in places_list])
    res = extract(red.text, templates=_load_project_templates(projectId))

    fields = {}
    if want_model and (res.template is None or res.needs_review):
        fields = _model_extract_invoice(text=red.text)
    return _merge_extraction(res, fields, source="template")


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


# --- Auth / multi-tenant (task D1) -----------------------------------------
# Invite-only, minimal: email+password, bcrypt, HS256 JWT. No email sending —
# the owner hands the invite link over out of band. Route guards / 401 handling
# on the frontend land in D1b; until then these routes exist but nothing else
# is gated (matches the pre-D1 behaviour + the D6 "VPN-only" posture).

def get_current_user(authorization: Optional[str] = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = auth.decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get_user(claims.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


def _auth_response(user: User) -> AuthResponse:
    return AuthResponse(
        token=auth.create_access_token(user.id, {"email": user.email}),
        user=user,
        projects=db.list_projects_for_user(user.id),
    )


@app.post("/auth/login", response_model=AuthResponse)
def login(body: LoginRequest):
    found = db.get_user_password_hash(body.email)
    if not found or not auth.verify_password(body.password, found[1]):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    user = db.get_user(found[0])
    assert user is not None
    return _auth_response(user)


@app.get("/auth/me", response_model=AuthResponse)
def whoami(user: User = Depends(get_current_user)):
    # Re-issues a fresh token — cheap "refresh" for the minimal cut.
    return _auth_response(user)


@app.post("/auth/invite", response_model=Invite, status_code=201)
def create_invite(body: CreateInviteRequest, user: User = Depends(get_current_user)):
    if not db.is_project_member(body.projectId, user.id):
        raise HTTPException(status_code=403, detail="Not a member of that project")
    if db.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="That email already has an account")
    raw = auth.new_invite_token()
    invite = db.create_invite(
        id=uuid.uuid4().hex, email=body.email, name=body.name, project_id=body.projectId,
        role=body.role, token_hash=auth.hash_invite_token(raw), created_at=now_iso(),
    )
    # The raw token is returned ONCE, here, for the owner to build the invite link.
    out = invite.model_dump()
    out["token"] = raw
    return JSONResponse(status_code=201, content=out)


@app.get("/auth/invites", response_model=List[Invite])
def list_invites(projectId: str, user: User = Depends(get_current_user)):
    if not db.is_project_member(projectId, user.id):
        raise HTTPException(status_code=403, detail="Not a member of that project")
    return db.list_invites(projectId)


@app.delete("/auth/invites/{id}", status_code=204)
def revoke_invite(id: str, user: User = Depends(get_current_user)):
    inv = db.get_invite(id)
    if inv and db.is_project_member(inv.projectId, user.id):
        db.delete_invite(id)
    return


@app.post("/auth/accept-invite", response_model=AuthResponse)
def accept_invite(body: AcceptInviteRequest):
    invite = db.get_invite_by_token_hash(auth.hash_invite_token(body.token))
    if invite is None or invite.acceptedAt is not None:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    existing = db.get_user_by_email(invite.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="That email already has an account")
    user = db.create_user(
        id=uuid.uuid4().hex, email=invite.email,
        name=body.name or invite.name or invite.email.split("@")[0],
        password_hash=auth.hash_password(body.password), avatar=None, created_at=now_iso(),
    )
    db.add_project_member(invite.projectId, user.id, invite.role)
    db.mark_invite_accepted(invite.id, now_iso())
    return _auth_response(user)


@app.post("/auth/change-password", status_code=204)
def change_password(body: LoginRequest, user: User = Depends(get_current_user)):
    # `body.email` is ignored; the caller is identified by the token. Reuses
    # LoginRequest so the client sends {email, password:<new>}.
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    db.set_user_password(user.id, auth.hash_password(body.password))
    return


# --- Browser-LLM automation (task E5) -------------------------------------
#
# Thin wrappers over `llm.providers.run_text(...)`. The heavy lifting (one
# persistent logged-in browser per provider, driven from its own worker
# thread) is in PropFlow/llm/. Every `LLMError` becomes a clean 503, never a
# 500 stack trace. The one-time provider login is done out of band via
# scripts/propflow_login_vnc.sh -> POST /ai/login.

_INVOICE_PROMPT = (
    "You are reading a Romanian utility invoice. Personal data has been redacted "
    "as [redacted] — ignore those. Reply with ONLY a JSON object, no prose, no code "
    "fence, with these keys: vendor (string), amount (number, the current total to "
    "pay, in lei), date (string 'YYYY-MM-DD', the invoice/issue date), dueDate "
    "(string 'YYYY-MM-DD' or null), category (one of \"Utilities\",\"Maintenance\","
    "\"Tax\",\"Insurance\",\"Other\"), subcategory (e.g. \"Electricity\",\"Gas\","
    "\"Water\",\"Internet\",\"Trash\" or null). Use null when a value isn't present.\n\n"
)


def _ai_error(exc: Exception):
    from llm import LLMNotLoggedIn, LLMRateLimited, LLMUnavailable

    if isinstance(exc, LLMNotLoggedIn):
        return HTTPException(status_code=503, detail="ai_not_logged_in")
    if isinstance(exc, LLMRateLimited):
        return HTTPException(status_code=503, detail="ai_rate_limited")
    if isinstance(exc, LLMUnavailable):
        return HTTPException(status_code=503, detail="ai_unavailable")
    return HTTPException(status_code=503, detail=f"ai_error: {exc}")


def _model_extract_invoice(*, text: Optional[str] = None,
                           image_png: Optional[bytes] = None) -> dict:
    """Ask the browser LLM to read one invoice. Returns a partial
    ParsedInvoice-ish dict, or {} on any failure (caller keeps what it had)."""
    from llm import extract_json_object, providers

    prompt = _INVOICE_PROMPT + (f"Invoice text:\n{text}" if text else "See the attached image.")
    try:
        answer = providers.run_text(lambda c: c.ask(prompt, image_png=image_png))
    except Exception:
        return {}
    data = extract_json_object(answer) or {}
    out: dict = {}
    if isinstance(data.get("vendor"), str) and data["vendor"].strip():
        out["vendor"] = data["vendor"].strip()
    if isinstance(data.get("amount"), (int, float)):
        out["amount"] = round(float(data["amount"]), 2)
    for k in ("date", "dueDate", "subcategory"):
        if isinstance(data.get(k), str) and data[k].strip():
            out[k] = data[k].strip()
    if data.get("category") in ("Utilities", "Maintenance", "Tax", "Insurance", "Other"):
        out["category"] = data["category"]
    return out


@app.get("/ai/status")
def ai_status():
    from llm import providers

    return providers.status()


@app.post("/ai/login")
def ai_login(provider: str = Form(...)):
    from llm import providers

    try:
        return providers.login(provider)
    except Exception as e:
        raise _ai_error(e)


@app.post("/ai/message")
def ai_message(body: dict):
    """Browser fallback for `generateTenantCommunication` (E6). The frontend
    composes the prompt and posts `{prompt}`; we return `{text}`."""
    prompt = (body or {}).get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt is required")
    from llm import providers

    try:
        return {"text": providers.run_text(lambda c: c.ask(prompt))}
    except Exception as e:
        raise _ai_error(e)


@app.post("/ai/extract-invoice", response_model=InvoiceExtraction)
async def ai_extract_invoice(
    file: Optional[UploadFile] = File(None),
    documentId: Optional[str] = Form(None),
    names: Optional[str] = Form(None),
    places: Optional[str] = Form(None),
):
    """Force the model path for one invoice (image, scanned PDF, or a vendor no
    template knows). PII is redacted before anything is sent."""
    data, is_pdf = await _invoice_bytes(file, documentId)
    names_list, places_list = _split_names(names), _split_names(places)

    if is_pdf:
        from invoice import pdf_to_text, redact

        try:
            raw = pdf_to_text(data)
        except Exception:
            raise HTTPException(status_code=422, detail="could not read the PDF")
        red = redact(raw, names=names_list, extra=[re.escape(p) for p in places_list])
        fields = _model_extract_invoice(text=red.text)
    else:
        fields = _model_extract_invoice(image_png=data)

    if not fields:
        raise HTTPException(status_code=503, detail="ai_error: no usable answer")
    return _merge_extraction(None, fields, source="model")


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
