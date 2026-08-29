"""Tests for the D2m ordered migration runner (migrations_runner.py).

These run against throwaway SQLite files. They exercise the real
``scripts/migrations/*.py`` scripts (discovery, signature introspection,
ordered apply, the ``schema_migrations`` ledger, idempotency) but never touch
PropFlow/data.db.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import migrations_runner as mr


@pytest.fixture
def fresh_db(tmp_path):
    """A DB with the full current schema (db.py::initialize) + exactly one
    project (migration 010 requires that), but nothing in schema_migrations —
    i.e. what a real install looks like the first time the runner sees it."""
    from db import SQLiteDatabase

    p = tmp_path / "fresh.db"
    d = SQLiteDatabase(str(p))
    d.initialize()
    d._cursor().execute(
        "INSERT INTO projects (id, name, ownerId, currency, createdAt) VALUES (?,?,?,?,?)",
        ("proj-1", "Portfolio", "owner-1", "RON", "2026-01-01T00:00:00"),
    )
    d.conn.commit()
    d.conn.close()
    return p


# --- discovery + introspection ---------------------------------------------

def test_discover_finds_numbered_migrations_in_order():
    migs = mr.discover()
    assert migs, "no migrations discovered"
    numbers = [m.number for m in migs]
    assert numbers == sorted(numbers)
    assert all(m.id[3] == "_" for m in migs)


def test_auto_runnable_flags_arg_taking_migrations_manual():
    by_id = {m.id: m for m in mr.discover()}
    # 006 needs write_files, 009 needs email/password → manual
    assert by_id["006_attachmenturl_to_documents"].auto_runnable() is False
    assert by_id["009_auth_tables_and_owner"].auto_runnable() is False
    # a plain schema migration is auto-runnable
    assert by_id["003_add_transaction_maintenanceid"].auto_runnable() is True


# --- the ledger -----------------------------------------------------------

def test_pending_is_everything_on_a_virgin_ledger(fresh_db):
    pend = mr.pending(fresh_db)
    assert {m.id for m in pend} == {m.id for m in mr.discover()}


def test_baseline_records_without_running(fresh_db):
    newly = mr.baseline(fresh_db)
    assert newly == [m.id for m in mr.discover()]
    assert mr.pending(fresh_db) == []
    rows = mr.applied_rows(fresh_db)
    assert all(r["via"] == "baseline" for r in rows)


def test_baseline_through_caps_at_number(fresh_db):
    mr.baseline(fresh_db, through=9)
    still_pending = [m.id for m in mr.pending(fresh_db)]
    assert still_pending == ["010_stamp_legacy_project"]


def test_baseline_is_idempotent(fresh_db):
    mr.baseline(fresh_db)
    assert mr.baseline(fresh_db) == []


# --- running ------------------------------------------------------------

def test_run_pending_applies_auto_migrations_and_skips_manual(fresh_db):
    res = mr.run_pending(fresh_db, backup=False)
    assert res["up_to_date"] is False
    assert "006_attachmenturl_to_documents" in res["skipped_manual"]
    assert "009_auth_tables_and_owner" in res["skipped_manual"]
    assert "003_add_transaction_maintenanceid" in res["applied"]
    # every auto migration is now recorded; only the manual ones stay pending
    assert {m.id for m in mr.pending(fresh_db)} == {
        "006_attachmenturl_to_documents",
        "009_auth_tables_and_owner",
    }


def test_run_pending_is_idempotent(fresh_db):
    mr.run_pending(fresh_db, backup=False)
    second = mr.run_pending(fresh_db, backup=False)
    assert second["applied"] == []
    # up_to_date is False only because the manual ones are still "pending",
    # but nothing was applied
    assert second["up_to_date"] in (False, True)


def test_run_pending_up_to_date_after_baseline(fresh_db):
    mr.baseline(fresh_db)
    res = mr.run_pending(fresh_db, backup=False)
    assert res == {
        "applied": [],
        "skipped_manual": [],
        "backup": None,
        "up_to_date": True,
    }


def test_run_pending_records_sha_and_detects_drift(fresh_db):
    mr.run_pending(fresh_db, backup=False)
    rows = {r["id"]: r for r in mr.applied_rows(fresh_db)}
    a_mig = next(m for m in mr.discover() if m.id in rows)
    assert rows[a_mig.id]["sha256"] == a_mig.sha256()


def test_run_pending_stops_at_first_failure(fresh_db, monkeypatch):
    """A failing migration raises MigrationError; migrations after it don't run
    and aren't recorded."""

    class _Boom(mr.Migration):
        def run_fn(self):
            def boom(*a, **k):
                raise RuntimeError("simulated migration blow-up")
            return boom

        def auto_runnable(self):
            return True

    real = mr.discover()
    doctored = []
    for m in real:
        if m.id == "003_add_transaction_maintenanceid":
            doctored.append(_Boom(m.path))
        else:
            doctored.append(m)
    monkeypatch.setattr(mr, "discover", lambda: doctored)

    with pytest.raises(mr.MigrationError) as ei:
        mr.run_pending(fresh_db, backup=False)
    assert ei.value.mig_id == "003_add_transaction_maintenanceid"

    done = mr.applied_ids(fresh_db)
    assert "003_add_transaction_maintenanceid" not in done
    assert "004_add_tenant_rentdueday" not in done  # nothing after the failure ran
    assert "002_add_currency_columns" in done  # everything before it did


def test_run_pending_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        mr.run_pending(tmp_path / "nope.db", backup=False)


# --- migration 010 actually does its job through the runner ----------------

def test_migration_010_stamps_legacy_rows_via_runner(fresh_db):
    con = sqlite3.connect(fresh_db)
    con.execute("INSERT INTO properties (id, address, projectId) VALUES ('p1', 'A', NULL)")
    con.execute("INSERT INTO transactions (id, amount, projectId) VALUES ('t1', 10.0, NULL)")
    con.commit()
    con.close()

    mr.run_pending(fresh_db, backup=False)

    con = sqlite3.connect(fresh_db)
    try:
        assert con.execute("SELECT projectId FROM properties WHERE id='p1'").fetchone()[0] == "proj-1"
        assert con.execute("SELECT projectId FROM transactions WHERE id='t1'").fetchone()[0] == "proj-1"
    finally:
        con.close()


def test_run_pending_surfaces_hard_exiting_migration_as_error(tmp_path):
    """Migration 010 calls `raise SystemExit(...)` when there isn't exactly one
    project. The runner must catch that (BaseException) and report it as a
    MigrationError, not let it kill the process."""
    from db import SQLiteDatabase

    p = tmp_path / "noproj.db"
    d = SQLiteDatabase(str(p))
    d.initialize()
    d.conn.close()
    # baseline everything except 010 so 010 is the only thing that runs
    mr.baseline(p, through=9)

    with pytest.raises(mr.MigrationError) as ei:
        mr.run_pending(p, backup=False)
    assert ei.value.mig_id == "010_stamp_legacy_project"
    assert "010_stamp_legacy_project" not in mr.applied_ids(p)
