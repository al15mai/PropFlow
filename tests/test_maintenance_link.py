"""transactions.maintenanceId — the expense ↔ maintenance-request link (task E3)."""
from __future__ import annotations


def test_maintenance_id_round_trips_through_create_and_list(client, make_tx):
    client.post("/transactions", json=make_tx(id="m1", category="Maintenance",
                                              maintenanceId="req-42"))
    client.post("/transactions", json=make_tx(id="m2", maintenanceId=None))

    by_id = {t["id"]: t for t in client.get("/transactions").json()}
    assert by_id["m1"]["maintenanceId"] == "req-42"
    assert by_id["m2"]["maintenanceId"] is None


def test_list_transactions_filters_by_maintenance_id(client, make_tx):
    client.post("/transactions", json=make_tx(id="a", maintenanceId="req-1"))
    client.post("/transactions", json=make_tx(id="b", maintenanceId="req-1"))
    client.post("/transactions", json=make_tx(id="c", maintenanceId="req-2"))
    client.post("/transactions", json=make_tx(id="d"))

    got = sorted(t["id"] for t in client.get("/transactions?maintenanceId=req-1").json())
    assert got == ["a", "b"]
    assert [t["id"] for t in client.get("/transactions?maintenanceId=req-2").json()] == ["c"]


def test_update_can_set_and_clear_the_link(client, make_tx):
    client.post("/transactions", json=make_tx(id="u1"))

    client.put("/transactions/u1", json=make_tx(id="u1", maintenanceId="req-9"))
    assert client.get("/transactions").json()[0]["maintenanceId"] == "req-9"

    client.put("/transactions/u1", json=make_tx(id="u1", maintenanceId=None))
    assert client.get("/transactions").json()[0]["maintenanceId"] is None


def test_link_survives_alongside_the_property_resolution(client, make_tx):
    """maintenanceId must not interfere with the tenant->property backfill (A2/A3)."""
    client.post("/transactions", json=make_tx(id="p1", propertyId=None, tenantId="t1",
                                              maintenanceId="req-7"))
    row = client.get("/transactions").json()[0]
    assert row["maintenanceId"] == "req-7"
