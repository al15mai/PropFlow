"""Shared pytest fixtures for the PropFlow backend.

Every test runs against a throwaway SQLite file in a tmp dir. Nothing here ever
opens the real PropFlow/data.db for writing. See ../../CLAUDE.md.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

# Put PropFlow/ (the package root: db.py, models.py, api.py) on sys.path.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

LIVE_DB = BACKEND_ROOT / "data.db"


@pytest.fixture(autouse=True)
def _safe_cwd(tmp_path, monkeypatch):
    """Isolate every test from the production DB, two ways:

    - ``PROPFLOW_DB`` points api.py at a throwaway file, so importing that module
      (it calls ``db.initialize()`` at import time) never opens PropFlow/data.db.
    - chdir into a tmp dir as a backstop for any code that still resolves a bare
      ``data.db`` relative to cwd.
    """
    monkeypatch.setenv("PROPFLOW_DB", str(tmp_path / "api-import.db"))
    monkeypatch.setenv("PROPFLOW_UPLOADS", str(tmp_path / "uploads"))  # task E8
    monkeypatch.setenv("PROPFLOW_BROWSER_PROFILES", str(tmp_path / "profiles"))  # task E5
    # No test should ever launch a real browser. Force the API-only path for the
    # AI fallbacks; the E5 route tests monkeypatch `llm.providers.run_text`.
    monkeypatch.setenv("AI_INVOICE_MODE", "api")   # task E5
    monkeypatch.setenv("AI_MESSAGE_MODE", "api")   # task E5
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def database(db_path):
    from db import SQLiteDatabase

    d = SQLiteDatabase(str(db_path))
    d.initialize()
    yield d
    if d.conn is not None:
        d.conn.close()


@pytest.fixture
def client(db_path, monkeypatch):
    """HTTP client wired to the real FastAPI app + a fresh per-test DB."""
    import db as db_mod
    import api as api_mod

    from _asgi import ASGIClient

    fresh = db_mod.SQLiteDatabase(str(db_path))
    fresh.initialize()
    monkeypatch.setattr(api_mod, "db", fresh)
    c = ASGIClient(api_mod.app)
    yield c
    c.close()
    if fresh.conn is not None:
        fresh.conn.close()


@pytest.fixture
def make_tx():
    """Factory for a valid Transaction dict (API payload shape)."""

    def _make(**overrides):
        base = {
            "id": uuid.uuid4().hex[:9],
            "date": "2026-01-15",
            "amount": 100.0,
            "type": "Expense",
            "category": "Utilities",
            "subcategory": "Gas",
            "description": "Test gas bill",
            "propertyId": "prop-1",
            "tenantId": "tenant-1",
            "paymentMethod": "Cash",
            "isReimbursable": True,
            "isPaid": False,
        }
        base.update(overrides)
        return base

    return _make


@pytest.fixture
def live_db_path() -> Path:
    if not LIVE_DB.exists():
        pytest.skip("live PropFlow/data.db not present")
    return LIVE_DB
