"""Characterization tests for the FastAPI transaction routes."""
from __future__ import annotations

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_list_transaction(client, make_tx):
    payload = make_tx(id="tx-api-1")
    r = client.post("/transactions", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "tx-api-1"

    r = client.get("/transactions")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert ids == ["tx-api-1"]


def test_list_transactions_query_filters(client, make_tx):
    client.post("/transactions", json=make_tx(id="a", type="Expense", tenantId="t1",
                                              date="2026-01-01"))
    client.post("/transactions", json=make_tx(id="b", type="Income", tenantId="t2",
                                              date="2026-02-01", category=None))

    assert [t["id"] for t in client.get("/transactions?type=Income").json()] == ["b"]
    assert [t["id"] for t in client.get("/transactions?tenantId=t1").json()] == ["a"]
    assert [t["id"] for t in
            client.get("/transactions?startDate=2026-01-15&endDate=2026-03-01").json()] == ["b"]


def test_update_transaction(client, make_tx):
    client.post("/transactions", json=make_tx(id="u1", amount=10.0))
    r = client.put("/transactions/u1", json=make_tx(id="u1", amount=42.0, description="edited"))
    assert r.status_code == 200
    assert client.get("/transactions").json()[0]["amount"] == 42.0


def test_update_missing_transaction_404(client, make_tx):
    r = client.put("/transactions/ghost", json=make_tx(id="ghost"))
    assert r.status_code == 404


def test_delete_transaction_204(client, make_tx):
    client.post("/transactions", json=make_tx(id="d1"))
    r = client.delete("/transactions/d1")
    assert r.status_code == 204
    assert client.get("/transactions").json() == []


# NOTE: api.py's RequestValidationError handler calls `await request.body()`, which
# hangs under httpx.ASGITransport (the body was already consumed and no further
# ASGI `receive` arrives). It works fine under uvicorn in prod. So the 422 *shape*
# isn't asserted here; validation itself is covered at the model layer below and
# in test_db.py. Revisit if we get a working TestClient (see task C6 / uv).

def test_invalid_transaction_type_is_rejected_by_the_model(make_tx):
    import pydantic
    from models import Transaction

    with pytest.raises(pydantic.ValidationError):
        Transaction(**make_tx(type="Bogus"))


def test_missing_required_field_is_rejected_by_the_model(make_tx):
    import pydantic
    from models import Transaction

    bad = make_tx()
    del bad["paymentMethod"]
    with pytest.raises(pydantic.ValidationError):
        Transaction(**bad)


def test_unknown_fields_are_ignored(client, make_tx):
    # models.Transaction has `extra = "ignore"`
    payload = make_tx(id="x1")
    payload["someClientOnlyField"] = "whatever"
    payload["projectId"] = client.owner_project_id
    r = client.post("/transactions", json=payload)
    assert r.status_code == 200


def test_description_defaults_to_empty_string(client, make_tx):
    payload = make_tx(id="nd")
    payload["description"] = None
    r = client.post("/transactions", json=payload)
    assert r.status_code == 200
    assert client.get("/transactions").json()[0]["description"] == ""
