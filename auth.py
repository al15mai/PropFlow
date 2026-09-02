"""Minimal auth primitives for task D1 — password hashing + JWT.

Pure functions: no FastAPI, no DB. `api.py` builds the `get_current_user`
dependency and the `/auth/*` routes on top of this.

Design (D1 "minimal auth machinery" decision):
  - invite-only, no open sign-up, no email sending
  - bcrypt password hash (sha256-prehashed so the 72-byte bcrypt limit and any
    NUL bytes never matter), HS256 JWT, signing key from `$PROPFLOW_JWT_SECRET`
  - one long-ish-lived access token + a `/auth/refresh` that reissues while valid;
    no separate refresh token in this cut.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import time
from typing import Any, Optional

import bcrypt
import jwt

JWT_ALG = "HS256"
ACCESS_TOKEN_TTL = 7 * 24 * 3600  # seconds

_DEV_SECRET = "dev-only-insecure-change-me"

# Tenant sub-claims are prefixed so a tenant token can never be mistaken for a
# landlord/user token (and vice-versa) even if the ids collide.
TENANT_SUB_PREFIX = "tenant:"


def _secret() -> str:
    s = os.environ.get("PROPFLOW_JWT_SECRET")
    if not s:
        # Loud in prod, tolerable for local dev / the test suite.
        print(
            "WARNING: $PROPFLOW_JWT_SECRET is not set — using an insecure dev key. "
            "Set it before exposing the API.",
            file=sys.stderr,
        )
        return _DEV_SECRET
    return s


# --- passwords -------------------------------------------------------------

def _prehash(password: str) -> bytes:
    """sha256 -> base64 (always 44 bytes, no NULs) so bcrypt's 72-byte cap and
    NUL-truncation quirk can never bite."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# Ambiguity-free alphabet — no 0/O/1/l/I — so a password read aloud or copied by
# hand doesn't get fat-fingered (task D1f, tenant passwords are handed over
# verbally / on paper).
_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz"


def generate_password(length: int = 10) -> str:
    """A random password for a freshly created / reset tenant account. Returned
    to the landlord exactly once; only its bcrypt hash is ever stored."""
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


# --- tokens ---------------------------------------------------------------

def create_access_token(sub: str, extra: Optional[dict[str, Any]] = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"sub": sub, "iat": now, "exp": now + ACCESS_TOKEN_TTL}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def create_tenant_token(tenant_id: str, extra: Optional[dict[str, Any]] = None) -> str:
    """A tenant access token: `sub = "tenant:<id>"`, `scope = "tenant"` (task
    D1f). `api.py::get_current_tenant` is the only thing that accepts it; every
    landlord route rejects it because `db.get_user("tenant:<id>")` is None."""
    payload = {"scope": "tenant"}
    if extra:
        payload.update(extra)
    return create_access_token(f"{TENANT_SUB_PREFIX}{tenant_id}", payload)


def decode_token(token: str) -> dict[str, Any]:
    """Return the claims, or raise `jwt.InvalidTokenError` (incl. expiry)."""
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])


def tenant_id_from_claims(claims: dict[str, Any]) -> Optional[str]:
    """The tenant id if these are tenant-token claims, else None."""
    sub = claims.get("sub", "")
    if claims.get("scope") == "tenant" and sub.startswith(TENANT_SUB_PREFIX):
        return sub[len(TENANT_SUB_PREFIX):]
    return None


# --- invite tokens ------------------------------------------------------------

def new_invite_token() -> str:
    """Opaque, URL-safe. Stored hashed; the raw value goes to the invitee once."""
    return base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- phone normalization (tenant login by phone, task D1f) -------------------

def normalize_phone(raw: str) -> str:
    """Reduce a Romanian phone number to a canonical form for matching:
    strip spaces / dashes / parens, and fold the `+40` / `0040` / leading-`0`
    prefixes to a bare national number. `+40 712 345 678`, `0712345678` and
    `0040712345678` all normalize to `712345678`. Non-RO numbers just lose their
    separators. Empty in -> empty out."""
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    digits = digits.replace("+", "")
    if digits.startswith("0040"):
        digits = digits[4:]
    elif digits.startswith("40") and len(digits) > 9:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits
