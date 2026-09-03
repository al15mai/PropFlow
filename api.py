import hashlib
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Optional
from datetime import datetime


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Warm the Playwright install off the request path so the first /ai/* call
    # isn't the one that runs `playwright install chromium` (E5b). Fire-and-
    # forget; the client build re-checks anyway.
    def _warm():
        try:
            from llm.playwright_setup import ensure_playwright_ready

            ensure_playwright_ready()
        except Exception:
            pass

    threading.Thread(target=_warm, name="playwright-warmup", daemon=True).start()
    try:
        yield
    finally:
        # Close every browser on its own worker thread so Chromium doesn't
        # linger holding a profile lock after the API exits (E5b).
        try:
            from llm import providers

            providers.shutdown()
        except Exception:
            pass


app = FastAPI(lifespan=_lifespan)

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
    TenantLoginRequest,
    TenantChangePasswordRequest,
    TenantAuthResponse,
    TenantPasswordReset,
    TenantCreateResponse,
    AccountHolder,
)

from db import SQLiteDatabase
from system_update import get_git_status, run_update, schedule_self_restart
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


# --- Auth guards (task D1c) ----------------------------------------------------
# Defined before the data routes so `Depends(get_current_user)` resolves. The
# `/auth/*` handlers themselves live further down (after the token helpers).

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


def require_owner(user: User = Depends(get_current_user)) -> User:
    """The landlord — owner of at least one project. Gates destructive / global
    operations (D5b restart/update, and anything project-admin)."""
    if not db.user_owns_any_project(user.id):
        raise HTTPException(status_code=403, detail="Owner only")
    return user


def _visible_project_ids(user: User) -> list:
    return [p.id for p in db.list_projects_for_user(user.id)]


def _resolve_project(projectId: Optional[str], user: User) -> str:
    """Which project this request reads/writes. A `projectId` the caller isn't a
    member of -> 403. None -> the caller's (only) project. NULL-`projectId` rows
    stay visible to whichever project is resolved (db.py `_project_filter` is
    lenient, task D4b)."""
    mine = _visible_project_ids(user)
    if not mine:
        raise HTTPException(status_code=403, detail="No project — ask an owner for an invite")
    if projectId is None:
        return mine[0]
    if projectId not in mine:
        raise HTTPException(status_code=403, detail="Not a member of that project")
    return projectId


def _assert_owns_row(row_project_id: Optional[str], user: User, what: str) -> None:
    """A write/delete targeting a row: allowed if the row is shared (NULL project,
    legacy) or belongs to one of the caller's projects."""
    if row_project_id is not None and row_project_id not in _visible_project_ids(user):
        raise HTTPException(status_code=403, detail=f"{what} belongs to another workspace")


# --- Tenant auth guard (task D1f) --------------------------------------------
# A `scope=tenant` token identifies a row in `tenants`, not `users`. It's only
# accepted by routes that explicitly `Depends(get_current_tenant)`; every
# landlord route uses `get_current_user`, which rejects it (no matching user).

def _claims_from_header(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return auth.decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_tenant(authorization: Optional[str] = Header(default=None)):
    claims = _claims_from_header(authorization)
    tenant_id = auth.tenant_id_from_claims(claims)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Not a tenant token")
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Unknown tenant")
    return tenant


def _tenant_owns_property(tenant, property_id: Optional[str]) -> bool:
    return bool(property_id) and property_id == tenant.propertyId


# A few read-only routes serve BOTH a landlord and a signed-in tenant (the tenant
# portal reuses `DocumentManager`, task D1f). This resolves whichever token was
# sent; the route then scopes a tenant caller to their own rows.
def get_user_or_tenant(authorization: Optional[str] = Header(default=None)):
    claims = _claims_from_header(authorization)
    tenant_id = auth.tenant_id_from_claims(claims)
    if tenant_id is not None:
        tenant = db.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=401, detail="Unknown tenant")
        return ("tenant", tenant)
    user = db.get_user(claims.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return ("user", user)


# Health endpoint
@app.get("/health")
def health():
    return {"status": "ok"}


# Running git identity of this backend, for the Settings > Version card (task D5).
@app.get("/admin/version")
def admin_version():
    return get_git_status()


# --- Owner-only restart / update & restart (task D5b) ----------------------
# The process exits ~1.5s after responding; systemd `Restart=always` (D6) brings
# it back on the (possibly just-pulled) code. `require_owner` -> 403 "Owner only"
# for a non-owner, 401 if unauthenticated.

@app.post("/admin/restart")
def admin_restart(user: User = Depends(require_owner)):
    """Reload the API process without touching git — for an env/config change or
    a stuck process."""
    schedule_self_restart()
    return {"status": "restarting"}


@app.post("/admin/update")
def admin_update(user: User = Depends(require_owner)):
    """Fast-forward both repos to their tracked branches, run installs if a
    lockfile moved, run pending DB migrations if the backend moved, then restart
    if anything changed.

    - 409 if the backend tree is dirty or the pull isn't a fast-forward (nothing
      changed, not restarting).
    - 500 if a DB migration failed — the code is pulled but the process is
      deliberately NOT restarted (it would expect a schema the DB doesn't have);
      `detail.migrations` says which migration and where the pre-run backup is.
    """
    result = run_update()
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result.get("backend"))
    if result.get("status") == "migration_failed":
        raise HTTPException(status_code=500, detail=result)
    return result


# --- Properties ---
@app.get("/properties", response_model=List[Property])
def list_properties(
    type: Optional[str] = None,
    status: Optional[str] = None,
    projectId: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    return db.list_properties(type=type, status=status, projectId=_resolve_project(projectId, user))


@app.post("/properties", response_model=Property)
def create_property(p: Property, user: User = Depends(get_current_user)):
    p.projectId = _resolve_project(p.projectId, user)
    db.create_property(p)
    return p


@app.put("/properties/{id}", response_model=Property)
def update_property(id: str, p: Property, user: User = Depends(get_current_user)):
    existing = db.get_property(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Property not found")
    _assert_owns_row(existing.projectId, user, "Property")
    _assert_owns_row(p.projectId, user, "Property")
    db.update_property(id, p)
    return p


@app.delete("/properties/{id}", status_code=204)
def delete_property(id: str, user: User = Depends(get_current_user)):
    existing = db.get_property(id)
    if existing is not None:
        _assert_owns_row(existing.projectId, user, "Property")
        db.delete_property(id)
    return


# --- Tenants ---
@app.get("/tenants", response_model=List[Tenant])
def list_tenants(
    propertyId: Optional[str] = None,
    status: Optional[str] = None,
    projectId: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    return db.list_tenants(
        propertyId=propertyId, status=status, projectId=_resolve_project(projectId, user)
    )


@app.post("/tenants", response_model=TenantCreateResponse)
def create_tenant(t: Tenant, user: User = Depends(get_current_user)):
    t.projectId = _resolve_project(t.projectId, user)
    db.create_tenant(t)
    # Every new tenant gets a login straight away (task D1f): a random password,
    # forced-reset on first sign-in, returned here ONCE for the landlord to pass
    # on. Only the hash is stored.
    pw = auth.generate_password()
    db.set_tenant_password(t.id, auth.hash_password(pw), must_reset=True)
    created = db.get_tenant(t.id)
    assert created is not None
    return TenantCreateResponse(**created.model_dump(), initialPassword=pw)


@app.put("/tenants/{id}", response_model=Tenant)
def update_tenant(id: str, t: Tenant, user: User = Depends(get_current_user)):
    existing = db.get_tenant(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _assert_owns_row(existing.projectId, user, "Tenant")
    _assert_owns_row(t.projectId, user, "Tenant")
    db.update_tenant(id, t)
    return db.get_tenant(id) or t


@app.delete("/tenants/{id}", status_code=204)
def delete_tenant(id: str, user: User = Depends(get_current_user)):
    existing = db.get_tenant(id)
    if existing is not None:
        _assert_owns_row(existing.projectId, user, "Tenant")
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
    user: User = Depends(get_current_user),
):
    return db.list_transactions(
        startDate=startDate,
        endDate=endDate,
        type=type,
        propertyId=propertyId,
        tenantId=tenantId,
        maintenanceId=maintenanceId,
        projectId=_resolve_project(projectId, user),
    )


@app.post("/transactions", response_model=Transaction)
def create_transaction(tx: Transaction, user: User = Depends(get_current_user)):
    tx.projectId = _resolve_project(tx.projectId, user)
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
def update_transaction(id: str, tx: Transaction, user: User = Depends(get_current_user)):
    existing = db.get_transaction(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _assert_owns_row(existing.projectId, user, "Transaction")
    _assert_owns_row(tx.projectId, user, "Transaction")
    db.update_transaction(id, tx)
    return tx


@app.delete("/transactions/{id}", status_code=204)
def delete_transaction(id: str, user: User = Depends(get_current_user)):
    existing = db.get_transaction(id)
    if existing is not None:
        _assert_owns_row(existing.projectId, user, "Transaction")
        db.delete_transaction(id)
    return


# --- Maintenance ---
@app.get("/maintenance", response_model=List[MaintenanceRequest])
def list_maintenance(
    status: Optional[str] = None,
    propertyId: Optional[str] = None,
    tenantId: Optional[str] = None,
    projectId: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    return db.list_maintenance(
        status=status, propertyId=propertyId, tenantId=tenantId,
        projectId=_resolve_project(projectId, user),
    )


@app.post("/maintenance", response_model=MaintenanceRequest)
def create_maintenance(req: MaintenanceRequest, user: User = Depends(get_current_user)):
    req.projectId = _resolve_project(req.projectId, user)
    db.create_maintenance(req)
    return req


@app.put("/maintenance/{id}", response_model=MaintenanceRequest)
def update_maintenance(id: str, req: MaintenanceRequest, user: User = Depends(get_current_user)):
    existing = db.get_maintenance(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Maintenance request not found")
    _assert_owns_row(existing.projectId, user, "Maintenance request")
    _assert_owns_row(req.projectId, user, "Maintenance request")
    db.update_maintenance(id, req)
    return req


@app.delete("/maintenance/{id}", status_code=204)
def delete_maintenance(id: str, user: User = Depends(get_current_user)):
    existing = db.get_maintenance(id)
    if existing is not None:
        _assert_owns_row(existing.projectId, user, "Maintenance request")
        db.delete_maintenance(id)
    return


# --- Alerts ---
@app.get("/alerts", response_model=List[Alert])
def list_alerts(user: User = Depends(get_current_user)):
    return db.list_alerts()


# --- Settings ---
@app.get("/settings", response_model=LandlordSettings)
def get_settings(user: User = Depends(get_current_user)):
    """The landlord-settings row. Never saved yet -> blanks (not a dummy
    profile), so the Settings form shows an empty form on first run rather
    than fake data."""
    s = db.get_settings()
    if s is not None:
        return s
    return LandlordSettings(
        displayName="", email=user.email or "", phone="",
        companyName="", currency="RON", language="ro",
    )


@app.post("/settings", response_model=LandlordSettings)
def save_settings(s: LandlordSettings, user: User = Depends(require_owner)):
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

# An invoice attached by URL is downloaded so it behaves like an upload —
# previewable + extractable (task D8). Cap + timeout keep a hostile link cheap.
_URL_DOC_MAX_BYTES = 20 * 1024 * 1024
_URL_DOC_TIMEOUT_S = 15
_URL_DOC_OK_MIME = ("application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif")


def _url_host_is_public(host: str) -> bool:
    """SSRF guard: reject links that resolve to loopback / private / link-local
    ranges. Only used for the server-side invoice download."""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for *_, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


async def _download_url_as_file(url: str, doc_id: str) -> Optional[dict]:
    """Try to fetch `url` and store it under the uploads dir like an upload.
    Returns dict(filename, mime, size, path, sha256) on success, or None to let
    the caller fall back to storing a bare link."""
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not _url_host_is_public(parsed.hostname):
        return None

    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=_URL_DOC_TIMEOUT_S) as client:
            resp = await client.get(url, headers={"User-Agent": "PropFlow/1.0"})
        resp.raise_for_status()
    except Exception:
        return None

    data = resp.content
    if not data or len(data) > _URL_DOC_MAX_BYTES:
        return None

    mime = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if mime not in _URL_DOC_OK_MIME:
        # sniff a PDF even when the server mislabels it
        if data[:5] == b"%PDF-":
            mime = "application/pdf"
        else:
            return None

    cd = resp.headers.get("content-disposition", "")
    name = None
    if "filename=" in cd:
        name = cd.split("filename=", 1)[1].strip().strip('"') or None
    if not name:
        name = unquote(parsed.path.rsplit("/", 1)[-1]) or "download"
    ext = Path(name).suffix or _EXT_BY_MIME.get(mime, "")
    if not Path(name).suffix and ext:
        name = f"{name}{ext}"
    rel = f"{doc_id}{ext}"
    (_uploads_dir() / rel).write_bytes(data)
    return {
        "filename": name,
        "mime": mime,
        "size": len(data),
        "path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _doc_response(doc: Document) -> dict:
    """What the client gets back — includes a ready-to-use fetch URL."""
    out = doc.model_dump()
    out["fileUrl"] = f"/documents/{doc.id}/file" if doc.storage == "file" else doc.url
    return out


def _assert_tx_in_scope(transaction_id: Optional[str], user: User) -> None:
    """A document hangs off a transaction — it's in scope only if that
    transaction is (E8b tenant-scoping decision; enforced server-side in D1c).
    A `pending` (transaction-less) doc is allowed for any authed user."""
    if not transaction_id:
        return
    tx = db.get_transaction(transaction_id)
    if tx is not None:
        _assert_owns_row(tx.projectId, user, "That transaction")


def _assert_doc_write_in_scope(transaction_id: Optional[str], principal) -> None:
    """Create/update/delete of a document. A landlord is scoped by project; a
    tenant may only touch a document on one of their own transactions (a
    transaction-less `pending` doc is not something a tenant creates)."""
    kind, who = principal
    if kind == "tenant":
        if not transaction_id:
            raise HTTPException(status_code=403, detail="Attach the document to one of your transactions")
        tx = db.get_transaction(transaction_id)
        if tx is None or tx.tenantId != who.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return
    _assert_tx_in_scope(transaction_id, who)


@app.get("/documents")
def list_documents(
    transactionId: Optional[str] = None,
    tenantId: Optional[str] = None,
    pending: Optional[bool] = None,
    principal=Depends(get_user_or_tenant),
):
    kind, who = principal
    if kind == "tenant":
        # A tenant only ever sees documents on their own transactions. The SQL
        # `tenantId` filter enforces that; a `transactionId` narrows within it,
        # and `pending` (transaction-less) docs are never a tenant's.
        if transactionId is not None:
            tx = db.get_transaction(transactionId)
            if tx is None or tx.tenantId != who.id:
                return []
        return [_doc_response(d) for d in db.list_documents(transactionId, who.id, None)]
    if transactionId:
        _assert_tx_in_scope(transactionId, who)
    return [_doc_response(d) for d in db.list_documents(transactionId, tenantId, pending)]


@app.post("/documents", status_code=201)
async def create_document(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    transactionId: Optional[str] = Form(None),
    kind: str = Form("other"),
    note: str = Form(""),
    filename: Optional[str] = Form(None),
    principal=Depends(get_user_or_tenant),
):
    _assert_doc_write_in_scope(transactionId or None, principal)
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
        # Download it so it behaves like an upload — previewable + extractable
        # (task D8). Falls back to a bare link if the fetch fails or the content
        # isn't a PDF/image.
        got = await _download_url_as_file(url, doc_id)
        if got is not None:
            doc = Document(
                id=doc_id, transactionId=transactionId or None, kind=kind,
                filename=got["filename"], mime=got["mime"], size=got["size"],
                storage="file", path=got["path"], sha256=got["sha256"],
                url=url,  # keep the source link for provenance
                note=note, createdAt=created,
            )
        else:
            doc = Document(
                id=doc_id, transactionId=transactionId or None, kind=kind,
                filename=url.rsplit("/", 1)[-1] or "link", storage="link", url=url,
                note=note, createdAt=created,
            )
    else:
        raise HTTPException(status_code=422, detail="provide a file or a url")

    db.create_document(doc)
    out = _doc_response(doc)
    if url and doc.storage == "link":
        # the client shows a softer "saved as a link, couldn't download" message
        out["downloadFailed"] = True
    return out


@app.get("/documents/{id}/file")
def get_document_file(id: str, principal=Depends(get_user_or_tenant)):
    doc = db.get_document(id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    kind, who = principal
    if kind == "tenant":
        tx = db.get_transaction(doc.transactionId) if doc.transactionId else None
        if tx is None or tx.tenantId != who.id:
            raise HTTPException(status_code=404, detail="Document not found")
    else:
        _assert_tx_in_scope(doc.transactionId, who)
    if doc.storage != "file" or not doc.path:
        raise HTTPException(status_code=409, detail="This document is a link, not a stored file")
    fp = _uploads_dir() / doc.path
    if not fp.exists():
        raise HTTPException(status_code=410, detail="File missing on disk")
    return FileResponse(fp, media_type=doc.mime or "application/octet-stream", filename=doc.filename)


@app.put("/documents/{id}", response_model=Document)
def update_document(id: str, patch: dict, principal=Depends(get_user_or_tenant)):
    existing = db.get_document(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _assert_doc_write_in_scope(existing.transactionId, principal)
    if patch.get("transactionId"):
        _assert_doc_write_in_scope(patch["transactionId"], principal)
    try:
        return db.update_document(id, **patch)
    except KeyError:
        raise HTTPException(status_code=404, detail="Document not found")


@app.delete("/documents/{id}", status_code=204)
def delete_document(id: str, principal=Depends(get_user_or_tenant)):
    existing = db.get_document(id)
    if existing is not None:
        _assert_doc_write_in_scope(existing.transactionId, principal)
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
    user: User = Depends(get_current_user),
):
    projectId = _resolve_project(projectId, user)
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
def list_invoice_templates(projectId: Optional[str] = None, user: User = Depends(get_current_user)):
    return db.list_invoice_templates(_resolve_project(projectId, user))


@app.post("/invoice-templates", response_model=InvoiceTemplate, status_code=201)
def create_invoice_template(t: InvoiceTemplate, user: User = Depends(get_current_user)):
    from invoice.templates import TemplateSpecError, template_from_spec

    try:
        template_from_spec(t.spec, source=t.source)  # validate before storing
    except TemplateSpecError as e:
        raise HTTPException(status_code=422, detail=f"bad template: {e}")
    if not t.id:
        t.id = uuid.uuid4().hex
    if not t.createdAt:
        t.createdAt = now_iso()
    t.projectId = _resolve_project(t.projectId, user)
    return db.create_invoice_template(t)


@app.put("/invoice-templates/{id}", response_model=InvoiceTemplate)
def update_invoice_template(id: str, patch: dict, user: User = Depends(get_current_user)):
    from invoice.templates import TemplateSpecError, template_from_spec

    existing = db.get_invoice_template(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Invoice template not found")
    _assert_owns_row(existing.projectId, user, "Invoice template")
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
def delete_invoice_template(id: str, user: User = Depends(get_current_user)):
    existing = db.get_invoice_template(id)
    if existing is not None:
        _assert_owns_row(existing.projectId, user, "Invoice template")
        db.delete_invoice_template(id)
    return


# --- Auth / multi-tenant (task D1) -----------------------------------------
# Invite-only, minimal: email+password, bcrypt, HS256 JWT. No email sending —
# the owner hands the invite link over out of band. The token helpers +
# `get_current_user` / `require_owner` guards live near the top of this file
# (before the data routes); D1c applies them to every data route so a token is
# required and each caller sees only their project(s).

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


@app.get("/projects/{id}/members")
def list_project_members(id: str, user: User = Depends(get_current_user)):
    """[{id, name, email, role}] — for the Team screen (task D1d). Members only."""
    if not db.is_project_member(id, user.id):
        raise HTTPException(status_code=403, detail="Not a member of that project")
    return db.list_project_members(id)


@app.get("/projects/{id}/account-holders", response_model=List[AccountHolder])
def list_project_account_holders(id: str, user: User = Depends(get_current_user)):
    """Tenants of this project that have a login (task D9) — so the landlord can
    see who can sign in and reset a password. Project members only; a member of
    another project gets 403."""
    if not db.is_project_member(id, user.id):
        raise HTTPException(status_code=403, detail="Not a member of that project")
    return db.list_account_holder_tenants(id)


# --- Project admin (task D1e) --------------------------------------------------
# Owner-only project mutations behind the Team screen's danger zone. The owner
# check is per-project ("are you *this* project's owner?"), not the global
# `require_owner`, so a member who owns a *different* project still gets 403 here.

def _require_project_owner(project_id: str, user: User) -> None:
    if db.get_project_member_role(project_id, user.id) != "owner":
        raise HTTPException(status_code=403, detail="Only the project owner can do that")


@app.put("/projects/{id}", response_model=Project)
def update_project(id: str, patch: dict, user: User = Depends(get_current_user)):
    _require_project_owner(id, user)
    name = patch.get("name")
    currency = patch.get("currency")
    if name is not None and not str(name).strip():
        raise HTTPException(status_code=422, detail="Project name can't be empty")
    updated = db.update_project(id, name=str(name).strip() if name is not None else None,
                               currency=currency)
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@app.delete("/projects/{id}", status_code=204)
def delete_project(id: str, user: User = Depends(get_current_user)):
    _require_project_owner(id, user)
    if db.count_owned_projects(user.id) <= 1:
        raise HTTPException(status_code=409, detail="Can't delete your only project")
    n = db.project_row_count(id)
    if n:
        raise HTTPException(
            status_code=409,
            detail=f"Project still has {n} record(s) — move or delete them first",
        )
    db.delete_project(id)
    return


@app.delete("/projects/{id}/members/{userId}", status_code=204)
def remove_project_member(id: str, userId: str, user: User = Depends(get_current_user)):
    _require_project_owner(id, user)
    role = db.get_project_member_role(id, userId)
    if role is None:
        return  # already not a member — idempotent
    if role == "owner":
        raise HTTPException(status_code=409, detail="Can't remove the project owner")
    db.remove_project_member(id, userId)
    return


@app.post("/projects/{id}/transfer", response_model=Project)
def transfer_project(id: str, body: dict, user: User = Depends(get_current_user)):
    _require_project_owner(id, user)
    target = body.get("userId")
    if not target:
        raise HTTPException(status_code=422, detail="userId is required")
    if target == user.id:
        raise HTTPException(status_code=409, detail="You already own this project")
    if db.get_project_member_role(id, target) is None:
        raise HTTPException(status_code=409, detail="That user isn't a member of this project")
    db.set_project_owner(id, target)
    updated = db.get_project(id)
    assert updated is not None
    return updated


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


# --- Tenant authentication (task D1f) --------------------------------------
# Tenants are a separate table from `users`; they sign in with email OR phone +
# a password the landlord generated. A `scope=tenant` token only unlocks that
# tenant's own record + its transactions / documents / maintenance / property.

_TENANT_MIN_PASSWORD = 8


def _tenant_auth_response(tenant: Tenant) -> TenantAuthResponse:
    return TenantAuthResponse(
        token=auth.create_tenant_token(tenant.id, {"name": tenant.name}),
        tenant=tenant,
        mustReset=bool(tenant.mustReset),
    )


@app.post("/auth/tenant-login", response_model=TenantAuthResponse)
def tenant_login(body: TenantLoginRequest):
    found = db.find_tenant_by_identifier(body.identifier)
    if not found or not auth.verify_password(body.password, found[1]):
        raise HTTPException(status_code=401, detail="Wrong email/phone or password")
    tenant = db.get_tenant(found[0])
    assert tenant is not None
    return _tenant_auth_response(tenant)


@app.get("/auth/tenant/me", response_model=TenantAuthResponse)
def tenant_whoami(tenant: Tenant = Depends(get_current_tenant)):
    # Re-issues a fresh token — the cheap "refresh" (mirrors /auth/me).
    return _tenant_auth_response(tenant)


@app.post("/auth/tenant/change-password", status_code=204)
def tenant_change_password(
    body: TenantChangePasswordRequest, tenant: Tenant = Depends(get_current_tenant)
):
    current_hash = db.get_tenant_password_hash(tenant.id)
    if not current_hash or not auth.verify_password(body.currentPassword, current_hash):
        raise HTTPException(status_code=401, detail="Current password is wrong")
    if len(body.newPassword) < _TENANT_MIN_PASSWORD:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {_TENANT_MIN_PASSWORD} characters",
        )
    db.set_tenant_password(tenant.id, auth.hash_password(body.newPassword), must_reset=False)
    return


@app.post("/tenants/{id}/reset-password", response_model=TenantPasswordReset)
def reset_tenant_password(id: str, user: User = Depends(get_current_user)):
    """Landlord regenerates a tenant's password. Returns the new plaintext ONCE
    (like the invite link). Owner/member of the tenant's project only."""
    tenant = db.get_tenant(id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    _assert_owns_row(tenant.projectId, user, "Tenant")
    new_pw = auth.generate_password()
    db.set_tenant_password(id, auth.hash_password(new_pw), must_reset=True)
    return TenantPasswordReset(tenantId=id, password=new_pw)


# --- Tenant portal data (task D1f) ---------------------------------------------
# A tenant token reads its own slice through ONE endpoint rather than reusing the
# landlord list routes (which are `Depends(get_current_user)` and 401 a tenant
# token). Everything returned is filtered to this tenant server-side.

@app.get("/tenant/bootstrap")
def tenant_bootstrap(tenant: Tenant = Depends(get_current_tenant)):
    """{tenant, property, transactions, maintenance} for the signed-in tenant —
    the tenant-portal equivalent of the landlord's `fetchAllData`."""
    prop = db.get_property(tenant.propertyId) if tenant.propertyId else None
    txs = [t for t in db.list_transactions() if t.tenantId == tenant.id]
    maint = [m for m in db.list_maintenance() if m.tenantId == tenant.id]
    return {
        "tenant": tenant.model_dump(),
        "property": prop.model_dump() if prop else None,
        "transactions": [t.model_dump() for t in txs],
        "maintenance": [m.model_dump() for m in maint],
    }


def _stamp_for_tenant(obj, tenant: Tenant) -> None:
    """Force a tenant-submitted row onto this tenant + their property + project,
    ignoring whatever the client sent — a tenant can only ever write their own."""
    obj.tenantId = tenant.id
    obj.projectId = tenant.projectId
    if hasattr(obj, "propertyId"):
        obj.propertyId = tenant.propertyId


@app.post("/tenant/maintenance", response_model=MaintenanceRequest)
def tenant_create_maintenance(req: MaintenanceRequest, tenant: Tenant = Depends(get_current_tenant)):
    """A tenant files a maintenance request for their own unit (task D1f / E4)."""
    _stamp_for_tenant(req, tenant)
    db.create_maintenance(req)
    return req


@app.put("/tenant/maintenance/{id}", response_model=MaintenanceRequest)
def tenant_update_maintenance(id: str, req: MaintenanceRequest, tenant: Tenant = Depends(get_current_tenant)):
    existing = db.get_maintenance(id)
    if existing is None or existing.tenantId != tenant.id:
        raise HTTPException(status_code=404, detail="Maintenance request not found")
    _stamp_for_tenant(req, tenant)
    db.update_maintenance(id, req)
    return req


@app.delete("/tenant/maintenance/{id}", status_code=204)
def tenant_delete_maintenance(id: str, tenant: Tenant = Depends(get_current_tenant)):
    existing = db.get_maintenance(id)
    if existing is not None and existing.tenantId == tenant.id:
        db.delete_maintenance(id)
    return


@app.post("/tenant/payments", response_model=Transaction)
def tenant_record_payment(tx: Transaction, tenant: Tenant = Depends(get_current_tenant)):
    """A tenant records a rent/bill payment they made (task D1f / E4). Forced to
    Income, their own tenantId/property/project, regardless of the payload."""
    tx.type = "Income"
    _stamp_for_tenant(tx, tenant)
    db.create_transaction(tx)
    return tx


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

    # One line in the server log so "AI unavailable" in the UI is diagnosable
    # without attaching a debugger (E5c acceptance criterion).
    print(f"[ai] request failed: {type(exc).__name__}: {exc}")
    if isinstance(exc, LLMNotLoggedIn):
        return HTTPException(status_code=503, detail="ai_not_logged_in")
    if isinstance(exc, LLMRateLimited):
        return HTTPException(status_code=503, detail="ai_rate_limited")
    if isinstance(exc, LLMUnavailable):
        # Chromium won't launch / isn't installed — not a "try again" case.
        return HTTPException(status_code=503, detail=f"ai_unavailable: {exc}")
    # Any other LLMError (browser closed mid-task, composer not found, no answer
    # within the budget). `providers.run_text` has already rebuilt the browser
    # and retried once, so this is a real transient failure — the frontend
    # shows the message and lets the owner retry.
    return HTTPException(status_code=503, detail=f"ai_transient: {exc}")


# A full utility-invoice text layer runs 8–10 KB. Pasting all of it into a
# browser LLM's composer is slow and tips ChatGPT's editor into a state where the
# turn goes out empty and the answer poll times out. Every field we want (vendor,
# current total, issue + due dates) sits in the first page — this cap keeps the
# header and the totals box, drops the payment-history / legal-boilerplate tail.
_INVOICE_TEXT_CAP = 2500


def _model_extract_invoice(*, text: Optional[str] = None,
                           image_png: Optional[bytes] = None) -> dict:
    """Ask the browser LLM to read one invoice. Returns a partial
    ParsedInvoice-ish dict, or {} on any failure (caller keeps what it had)."""
    from llm import extract_json_object, providers

    if text and len(text) > _INVOICE_TEXT_CAP:
        text = text[:_INVOICE_TEXT_CAP]
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
def ai_status(user: User = Depends(get_current_user)):
    from llm import providers

    return providers.status()


@app.post("/ai/login")
def ai_login(provider: str = Form(...), user: User = Depends(require_owner)):
    from llm import providers

    try:
        return providers.login(provider)
    except Exception as e:
        raise _ai_error(e)


@app.post("/ai/message")
def ai_message(body: dict, user: User = Depends(get_current_user)):
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
    user: User = Depends(get_current_user),
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
