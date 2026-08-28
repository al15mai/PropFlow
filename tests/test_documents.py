"""Document store — DB layer + API routes (task E8)."""
from __future__ import annotations

import io

import pytest

from models import Document


# --- DB layer --------------------------------------------------------------

def _doc(**kw) -> Document:
    base = dict(
        id="d1", transactionId="tx1", kind="invoice", filename="inv.pdf",
        mime="application/pdf", size=10, storage="file", path="d1.pdf",
        sha256="abc", note="", createdAt="2026-01-01T00:00:00",
    )
    base.update(kw)
    return Document(**base)


def test_create_get_roundtrip(database):
    database.create_document(_doc())
    got = database.get_document("d1")
    assert got is not None
    assert got.filename == "inv.pdf" and got.storage == "file" and got.kind == "invoice"


def test_list_by_transaction_and_pending(database):
    database.create_document(_doc(id="a", transactionId="tx1"))
    database.create_document(_doc(id="b", transactionId="tx2"))
    database.create_document(_doc(id="p", transactionId=None))
    assert {d.id for d in database.list_documents(transactionId="tx1")} == {"a"}
    assert {d.id for d in database.list_documents(pending=True)} == {"p"}
    assert {d.id for d in database.list_documents(pending=False)} == {"a", "b"}


def test_list_by_tenant_joins_through_transactions(database):
    from models import Transaction
    database.create_transaction(Transaction(
        id="tx-ten", date="2026-01-01", amount=1, type="Expense",
        paymentMethod="Cash", tenantId="ten-9", propertyId="p1",
    ))
    database.create_document(_doc(id="d", transactionId="tx-ten"))
    database.create_document(_doc(id="other", transactionId="tx-nope"))
    assert {d.id for d in database.list_documents(tenantId="ten-9")} == {"d"}


def test_update_links_pending_doc_to_a_transaction(database):
    database.create_document(_doc(id="d", transactionId=None))
    out = database.update_document("d", transactionId="tx7", kind="receipt", note="scanned")
    assert out.transactionId == "tx7" and out.kind == "receipt" and out.note == "scanned"


def test_update_missing_raises(database):
    with pytest.raises(KeyError):
        database.update_document("nope", note="x")


def test_delete_returns_the_row(database):
    database.create_document(_doc(id="d"))
    removed = database.delete_document("d")
    assert removed is not None and removed.path == "d1.pdf"
    assert database.get_document("d") is None
    assert database.delete_document("d") is None  # already gone


# --- API routes ----------------------------------------------------------

def test_upload_file_stores_a_real_file_not_a_blob(client, tmp_path):
    files = {"file": ("bill.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    r = client.post("/documents", files=files, data={"transactionId": "tx1", "kind": "bill"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["storage"] == "file"
    assert body["size"] == len(b"%PDF-1.4 fake")
    assert body["sha256"]
    assert body["fileUrl"] == f"/documents/{body['id']}/file"

    # and it streams back
    f = client.get(body["fileUrl"])
    assert f.status_code == 200
    assert f.content == b"%PDF-1.4 fake"


def test_add_by_link(client):
    r = client.post("/documents", data={"url": "https://vendor.example/invoice/42.pdf",
                                        "transactionId": "tx1", "kind": "invoice"})
    assert r.status_code == 201
    body = r.json()
    assert body["storage"] == "link"
    assert body["url"] == "https://vendor.example/invoice/42.pdf"
    assert body["fileUrl"] == body["url"]
    # a link has no stored file
    assert client.get(f"/documents/{body['id']}/file").status_code == 409


def test_post_without_file_or_url_is_422(client):
    assert client.post("/documents", data={"kind": "other"}).status_code == 422


def test_list_filter_by_transaction(client):
    client.post("/documents", data={"url": "http://x/a", "transactionId": "tx-A"})
    client.post("/documents", data={"url": "http://x/b", "transactionId": "tx-B"})
    got = client.get("/documents", params={"transactionId": "tx-A"}).json()
    assert [d["url"] for d in got] == ["http://x/a"]


def test_link_pending_then_delete(client):
    pid = client.post("/documents", data={"url": "http://x/p"}).json()["id"]
    assert client.get("/documents", params={"pending": True}).json()[0]["id"] == pid
    client.put(f"/documents/{pid}", json={"transactionId": "tx9"})
    assert client.get("/documents", params={"pending": True}).json() == []
    assert client.delete(f"/documents/{pid}").status_code == 204
    assert client.get("/documents", params={"transactionId": "tx9"}).json() == []
