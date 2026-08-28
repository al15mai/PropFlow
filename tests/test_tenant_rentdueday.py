"""tenants.rentDueDay — the per-tenant rent due day used by the alerts engine (task E1)."""
from __future__ import annotations


def _tenant(**overrides):
    base = {
        "id": "t1",
        "propertyId": "p1",
        "name": "Ana",
        "email": "-",
        "phone": "-",
        "leaseStart": "2026-01-01",
        "leaseEnd": "2026-12-31",
        "deposit": 0,
        "status": "Active",
    }
    base.update(overrides)
    return base


def test_rent_due_day_round_trips_through_create_and_list(client):
    client.post("/tenants", json=_tenant(id="a", rentDueDay=10))
    client.post("/tenants", json=_tenant(id="b"))  # omitted -> null

    by_id = {t["id"]: t for t in client.get("/tenants").json()}
    assert by_id["a"]["rentDueDay"] == 10
    assert by_id["b"]["rentDueDay"] is None


def test_update_can_set_and_clear_the_due_day(client):
    client.post("/tenants", json=_tenant(id="u1"))

    client.put("/tenants/u1", json=_tenant(id="u1", rentDueDay=15))
    assert client.get("/tenants").json()[0]["rentDueDay"] == 15

    client.put("/tenants/u1", json=_tenant(id="u1", rentDueDay=None))
    assert client.get("/tenants").json()[0]["rentDueDay"] is None


def test_db_layer_round_trip(database):
    from models import Tenant

    database.create_tenant(Tenant(**_tenant(id="d1", rentDueDay=5)))
    (got,) = database.list_tenants()
    assert got.rentDueDay == 5
