"""D1d end-to-end: the seeded owner logs into a copy of the live DB and sees the
real portfolio; a fresh account in its own project sees none of the *stamped*
rows.

Runs against a COPY of PropFlow/data.db — never the live file. Skips when the
live DB (or its migration-009 seed) is absent, e.g. on CI.
"""
from __future__ import annotations

import shutil
import sqlite3
import uuid

import pytest

import auth


@pytest.fixture
def live_copy(live_db_path, tmp_path, monkeypatch):
    """A throwaway copy of the live DB wired into the API."""
    dst = tmp_path / "live-copy.db"
    shutil.copyfile(live_db_path, dst)
    import db as db_mod
    import api as api_mod
    from _asgi import ASGIClient

    fresh = db_mod.SQLiteDatabase(str(dst))
    fresh.initialize()  # idempotent; live already has every table
    monkeypatch.setattr(api_mod, "db", fresh)
    c = ASGIClient(api_mod.app)
    yield c, fresh
    c.close()
    if fresh.conn is not None:
        fresh.conn.close()


def _seeded_owner(fresh):
    row = fresh._cursor().execute(
        "SELECT u.id, u.email FROM users u "
        "JOIN project_members m ON m.userId = u.id AND m.role = 'owner' LIMIT 1"
    ).fetchone()
    if row is None:
        pytest.skip("live DB has no migration-009 owner seed yet")
    return row["id"], row["email"]


def test_seeded_owner_sees_the_real_portfolio(live_copy):
    client, fresh = live_copy
    owner_id, _email = _seeded_owner(fresh)
    tok = auth.create_access_token(owner_id, {})
    h = {"Authorization": f"Bearer {tok}"}

    props = client.get("/properties", headers=h).json()
    tenants = client.get("/tenants", headers=h).json()
    txns = client.get("/transactions", headers=h).json()

    # As of migration 009 the live portfolio is 2 / 2 / 98 (task CLAUDE.md).
    assert len(props) >= 2
    assert len(tenants) >= 2
    assert len(txns) >= 98
    assert round(sum(t["amount"] for t in txns), 2) != 0


def test_second_project_is_isolated_from_stamped_rows(live_copy):
    client, fresh = live_copy
    owner_id, _ = _seeded_owner(fresh)
    owner_project = fresh._cursor().execute(
        "SELECT projectId FROM project_members WHERE userId = ? AND role = 'owner'",
        (owner_id,),
    ).fetchone()["projectId"]

    # Simulate migration 010: stamp the legacy NULL-project rows onto the owner's
    # project. (The real migration is scripts/migrations/010; here we just prove
    # the isolation it unlocks.)
    cur = fresh._cursor()
    for tbl in ("properties", "tenants", "transactions", "maintenance"):
        cur.execute(f"UPDATE {tbl} SET projectId = ? WHERE projectId IS NULL", (owner_project,))
    fresh.conn.commit()

    # a brand-new account with its own project
    stranger = fresh.create_user(
        id=uuid.uuid4().hex, email="stranger@e2e.local", name="Stranger",
        password_hash=auth.hash_password("strangerpw1"), avatar=None,
        created_at="2026-08-29T00:00:00",
    )
    fresh.create_project(
        id=uuid.uuid4().hex, name="Empty", owner_id=stranger.id, currency="RON",
        created_at="2026-08-29T00:00:00",
    )
    tok = auth.create_access_token(stranger.id, {})
    h = {"Authorization": f"Bearer {tok}"}

    assert client.get("/properties", headers=h).json() == []
    assert client.get("/tenants", headers=h).json() == []
    assert client.get("/transactions", headers=h).json() == []

    # ...and the owner still sees everything
    otok = auth.create_access_token(owner_id, {})
    oh = {"Authorization": f"Bearer {otok}"}
    assert len(client.get("/transactions", headers=oh).json()) >= 98
