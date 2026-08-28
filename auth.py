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
import sys
import time
from typing import Any, Optional

import bcrypt
import jwt

JWT_ALG = "HS256"
ACCESS_TOKEN_TTL = 7 * 24 * 3600  # seconds

_DEV_SECRET = "dev-only-insecure-change-me"


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


# --- tokens ---------------------------------------------------------------

def create_access_token(sub: str, extra: Optional[dict[str, Any]] = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"sub": sub, "iat": now, "exp": now + ACCESS_TOKEN_TTL}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> dict[str, Any]:
    """Return the claims, or raise `jwt.InvalidTokenError` (incl. expiry)."""
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])


# --- invite tokens ------------------------------------------------------------

def new_invite_token() -> str:
    """Opaque, URL-safe. Stored hashed; the raw value goes to the invitee once."""
    return base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
