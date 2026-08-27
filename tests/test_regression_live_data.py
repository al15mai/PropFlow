"""Regression: push every real transaction from the live DB through
create_transaction / list_transactions and assert nothing is lost or mangled.

Skipped automatically when PropFlow/data.db is absent (e.g. CI). Read-only wrt
the live DB - all writes go to a tmp file.
"""
from __future__ import annotations

import sqlite3

from models import Transaction

FIELDS = [
    "id", "date", "amount", "type", "category", "subcategory", "description",
    "propertyId", "tenantId", "paymentMethod", "isReimbursable", "attachmentUrl", "isPaid",
]


def _load_live_transactions(live_db_path):
    con = sqlite3.connect(f"file:{live_db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM transactions")]
    con.close()
    return rows


def test_live_transactions_roundtrip_through_db_layer(database, live_db_path):
    rows = _load_live_transactions(live_db_path)
    assert len(rows) > 0

    for r in rows:
        database.create_transaction(Transaction(**{k: r.get(k) for k in FIELDS}))

    out = {t.id: t for t in database.list_transactions()}
    assert len(out) == len(rows)

    total_in = round(sum(r["amount"] for r in rows), 2)
    total_out = round(sum(t.amount for t in out.values()), 2)
    assert total_in == total_out

    for r in rows:
        t = out[r["id"]]
        assert t.amount == r["amount"]
        assert t.type == r["type"]
        assert t.date == r["date"]
        assert (t.tenantId or None) == (r["tenantId"] or None)
        assert bool(t.isReimbursable) == bool(r["isReimbursable"])
        assert bool(t.isPaid) == bool(r["isPaid"])


def test_live_transaction_types_are_known_values(live_db_path):
    rows = _load_live_transactions(live_db_path)
    assert {r["type"] for r in rows} <= {"Income", "Expense"}


def test_live_data_shape_snapshot(database, live_db_path):
    """Records the current shape of the production data. Update deliberately."""
    rows = _load_live_transactions(live_db_path)
    n_income = sum(1 for r in rows if r["type"] == "Income")
    n_expense = sum(1 for r in rows if r["type"] == "Expense")
    n_null_property_with_tenant = sum(1 for r in rows if r["tenantId"] and not r["propertyId"])

    # As of 2026-08-27, after migration 001: 98 rows, tenant-linked rows all have
    # a propertyId. Landlord-direct rows (no tenant) may still have none.
    assert len(rows) >= 98
    assert n_income + n_expense == len(rows)
    assert n_null_property_with_tenant == 0  # migration 001 backfilled these (task A3)
