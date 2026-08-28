"""Characterization tests for SQLiteDatabase transaction paths.

These pin CURRENT behavior (quirks included) so the branch reconciliation and any
refactor of db.py can be verified. When behavior changes on purpose, change the
assertion and note why.
"""
from __future__ import annotations

import sqlite3

import pytest

from models import Transaction


def mk(**kw) -> Transaction:
    base = dict(
        id="tx1",
        date="2026-01-15",
        amount=123.45,
        type="Expense",
        category="Utilities",
        subcategory="Gas",
        description="Gas bill",
        propertyId="p1",
        tenantId="t1",
        paymentMethod="Cash",
        isReimbursable=True,
        isPaid=False,
    )
    base.update(kw)
    return Transaction(**base)


# --- create / read round-trip -------------------------------------------------

def test_create_then_list_roundtrip(database):
    tx = mk()
    database.create_transaction(tx)
    rows = database.list_transactions()
    assert len(rows) == 1
    got = rows[0]
    assert got.id == "tx1"
    assert got.amount == 123.45
    assert got.type == "Expense"
    assert got.category == "Utilities"
    assert got.subcategory == "Gas"
    assert got.description == "Gas bill"
    assert got.propertyId == "p1"
    assert got.tenantId == "t1"
    assert got.paymentMethod == "Cash"
    assert got.isReimbursable is True
    assert got.isPaid is False


def test_bool_flags_are_persisted_as_int_and_coerced_back(database, db_path):
    database.create_transaction(mk(id="a", isReimbursable=True, isPaid=True))
    database.create_transaction(mk(id="b", isReimbursable=False, isPaid=False))

    raw = sqlite3.connect(db_path)
    stored = dict(
        (r[0], (r[1], r[2]))
        for r in raw.execute("SELECT id, isReimbursable, isPaid FROM transactions")
    )
    raw.close()
    assert stored["a"] == (1, 1)
    assert stored["b"] == (0, 0)

    by_id = {t.id: t for t in database.list_transactions()}
    assert by_id["a"].isReimbursable is True and by_id["a"].isPaid is True
    assert by_id["b"].isReimbursable is False and by_id["b"].isPaid is False


def test_none_description_stored_as_empty_string(database, db_path):
    database.create_transaction(mk(id="a", description=None))
    raw = sqlite3.connect(db_path)
    (desc,) = raw.execute("SELECT description FROM transactions WHERE id='a'").fetchone()
    raw.close()
    assert desc == ""  # db.py does `tx.description or ""`


def test_income_transaction_without_category(database):
    database.create_transaction(
        mk(id="inc", type="Income", category=None, subcategory=None,
           description="Rent", isReimbursable=False)
    )
    (got,) = database.list_transactions()
    assert got.type == "Income"
    assert got.category is None


# --- update / delete ---------------------------------------------------------

def test_update_transaction_changes_fields(database):
    database.create_transaction(mk())
    database.update_transaction("tx1", mk(amount=999.0, description="edited", isPaid=True))
    (got,) = database.list_transactions()
    assert got.amount == 999.0
    assert got.description == "edited"
    assert got.isPaid is True


def test_update_missing_transaction_raises_keyerror(database):
    with pytest.raises(KeyError):
        database.update_transaction("nope", mk(id="nope"))


# --- multi-currency columns (task A4) ---------------------------------------

def test_currency_defaults_backfilled_for_legacy_style_row(database):
    """A row created without currency info is treated as base: fxRate 1, amountBase == amount."""
    database.create_transaction(mk(amount=100.0))
    (got,) = database.list_transactions()
    assert got.fxRate == 1.0
    assert got.amountBase == 100.0
    assert got.currency is None


def test_currency_fields_roundtrip(database):
    database.create_transaction(mk(id="eur", amount=300.0, currency="EUR", fxRate=5.06))
    (got,) = database.list_transactions()
    assert got.currency == "EUR"
    assert got.fxRate == 5.06
    assert got.amountBase == 1518.0  # 300 * 5.06, derived server-side


def test_explicit_amount_base_is_respected(database):
    """The landlord can pin the exact RON they received instead of amount*fxRate."""
    database.create_transaction(mk(id="p", amount=1000.0, currency="EUR", fxRate=5.0, amountBase=4980.0))
    (got,) = database.list_transactions()
    assert got.amountBase == 4980.0


def test_update_recomputes_amount_base(database):
    database.create_transaction(mk(id="x", amount=100.0))
    database.update_transaction("x", mk(id="x", amount=200.0, currency="EUR", fxRate=5.0))
    (got,) = database.list_transactions()
    assert got.amountBase == 1000.0
    assert got.currency == "EUR"


def test_delete_transaction(database):
    database.create_transaction(mk())
    database.delete_transaction("tx1")
    assert database.list_transactions() == []


def test_delete_missing_transaction_is_silent(database):
    database.delete_transaction("nope")  # no raise


# --- filters ---------------------------------------------------------------

@pytest.fixture
def seeded(database):
    database.create_transaction(mk(id="e1", type="Expense", date="2026-01-01",
                                   propertyId="p1", tenantId="t1"))
    database.create_transaction(mk(id="e2", type="Expense", date="2026-02-01",
                                   propertyId="p2", tenantId="t2"))
    database.create_transaction(mk(id="i1", type="Income", date="2026-03-01",
                                   propertyId="p1", tenantId="t1", category=None))
    database.create_transaction(mk(id="i2", type="Income", date="2026-04-01",
                                   propertyId=None, tenantId="t1", category=None))
    return database


def test_filter_by_type(seeded):
    assert {t.id for t in seeded.list_transactions(type="Income")} == {"i1", "i2"}
    assert {t.id for t in seeded.list_transactions(type="Expense")} == {"e1", "e2"}


def test_filter_by_tenant(seeded):
    assert {t.id for t in seeded.list_transactions(tenantId="t1")} == {"e1", "i1", "i2"}


def test_filter_by_property_drops_null_property_rows(seeded):
    # i2 has propertyId=None -> excluded even though tenantId="t1". This is the
    # behavior behind ledger task A2 / data task A3.
    assert {t.id for t in seeded.list_transactions(propertyId="p1")} == {"e1", "i1"}


def test_filter_by_date_range_inclusive(seeded):
    got = {t.id for t in seeded.list_transactions(startDate="2026-02-01", endDate="2026-03-01")}
    assert got == {"e2", "i1"}


def test_filters_combine_with_and(seeded):
    got = {t.id for t in seeded.list_transactions(type="Income", tenantId="t1", propertyId="p1")}
    assert got == {"i1"}


def test_none_valued_filters_are_ignored(seeded):
    assert len(seeded.list_transactions(type=None, tenantId=None)) == 4


# --- propertyId auto-resolution (migration 001 / tasks A2, A3) ---------------

@pytest.fixture
def db_with_tenant(database):
    from models import Property, Tenant

    database.create_property(Property(
        id="unit-6", address="A", unitNumber="6", rooms=2, rentAmount=1600,
        currency="RON", status="Occupied", type="Rental",
    ))
    database.create_tenant(Tenant(
        id="ten-6", propertyId="unit-6", name="A", email="-", phone="-",
        leaseStart="2024-10-01", leaseEnd="2027-02-01", deposit=0, status="Active",
    ))
    return database


def test_create_fills_property_id_from_tenant_when_missing(db_with_tenant):
    db_with_tenant.create_transaction(mk(id="a", tenantId="ten-6", propertyId=None))
    (got,) = db_with_tenant.list_transactions()
    assert got.propertyId == "unit-6"


def test_create_keeps_explicit_property_id(db_with_tenant):
    db_with_tenant.create_transaction(mk(id="a", tenantId="ten-6", propertyId="unit-9"))
    (got,) = db_with_tenant.list_transactions()
    assert got.propertyId == "unit-9"


def test_landlord_direct_transaction_keeps_null_property(db_with_tenant):
    db_with_tenant.create_transaction(mk(id="a", tenantId=None, propertyId=None))
    (got,) = db_with_tenant.list_transactions()
    assert got.propertyId is None


def test_update_backfills_property_id(db_with_tenant):
    db_with_tenant.create_transaction(mk(id="a", tenantId=None, propertyId=None))
    db_with_tenant.update_transaction("a", mk(id="a", tenantId="ten-6", propertyId=None))
    (got,) = db_with_tenant.list_transactions()
    assert got.propertyId == "unit-6"


# --- project scoping (task D4b) --------------------------------------------

def _prop(**kw):
    from models import Property
    base = dict(id="p", address="A", unitNumber="1", rooms=1, rentAmount=1000,
                currency="RON", status="Vacant", type="Rental")
    base.update(kw)
    return Property(**base)


def _maint(**kw):
    from models import MaintenanceRequest
    base = dict(id="m", propertyId="p", title="x", description="y",
                priority="Low", status="Open", dateReported="2026-01-01")
    base.update(kw)
    return MaintenanceRequest(**base)


def test_transactions_scoped_by_project_do_not_leak(database):
    database.create_transaction(mk(id="a", projectId="proj-A"))
    database.create_transaction(mk(id="b", projectId="proj-B"))
    database.create_transaction(mk(id="legacy", projectId=None))

    a = {t.id for t in database.list_transactions(projectId="proj-A")}
    b = {t.id for t in database.list_transactions(projectId="proj-B")}
    assert a == {"a", "legacy"}   # own rows + shared/legacy NULL rows
    assert b == {"b", "legacy"}
    assert "b" not in a and "a" not in b


def test_no_project_filter_returns_every_transaction(database):
    database.create_transaction(mk(id="a", projectId="proj-A"))
    database.create_transaction(mk(id="b", projectId="proj-B"))
    assert {t.id for t in database.list_transactions()} == {"a", "b"}


def test_transaction_project_id_round_trips_and_update_preserves_it(database):
    database.create_transaction(mk(id="a", projectId="proj-A"))
    (got,) = database.list_transactions()
    assert got.projectId == "proj-A"
    # an edit that omits projectId (null) must not un-scope the row
    database.update_transaction("a", mk(id="a", amount=999, projectId=None))
    (got,) = database.list_transactions(projectId="proj-A")
    assert got.projectId == "proj-A" and got.amount == 999


def test_properties_scoped_by_project(database):
    database.create_property(_prop(id="pa", projectId="proj-A"))
    database.create_property(_prop(id="pb", projectId="proj-B"))
    database.create_property(_prop(id="shared", projectId=None))
    assert {p.id for p in database.list_properties(projectId="proj-A")} == {"pa", "shared"}
    assert {p.id for p in database.list_properties(projectId="proj-B")} == {"pb", "shared"}


def test_tenants_scoped_by_project(database):
    from models import Tenant
    def ten(i, pid):
        return Tenant(id=i, propertyId="p", name=i, email="-", phone="-",
                      leaseStart="2026-01-01", leaseEnd="2027-01-01", deposit=0,
                      status="Active", projectId=pid)
    database.create_tenant(ten("ta", "proj-A"))
    database.create_tenant(ten("tb", "proj-B"))
    assert {t.id for t in database.list_tenants(projectId="proj-A")} == {"ta"}


def test_maintenance_scoped_by_project(database):
    database.create_maintenance(_maint(id="ma", projectId="proj-A"))
    database.create_maintenance(_maint(id="mb", projectId="proj-B"))
    database.create_maintenance(_maint(id="shared", projectId=None))
    assert {m.id for m in database.list_maintenance(projectId="proj-A")} == {"ma", "shared"}
