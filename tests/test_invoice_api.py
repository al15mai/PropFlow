"""Invoice-template store + the /invoices/extract route (task E7)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from models import InvoiceTemplate

FIXTURES = Path(__file__).resolve().parents[2] / "services" / "__fixtures__" / "invoices"


def _spec(vendor="Electrica"):
    return {
        "vendor": vendor,
        "match": ["electrica sa"],
        "category": "Utilities",
        "subcategory": "Electricity",
        "fields": {
            "amount": {"after": "Total de plata", "kind": "money"},
            "date": {"after": "Data facturii", "kind": "date"},
        },
    }


# --- DB layer ----------------------------------------------------------

def test_template_crud_roundtrip(database):
    t = InvoiceTemplate(id="t1", vendor="Electrica", spec=_spec(), createdAt="2026-01-01")
    database.create_invoice_template(t)
    got = database.get_invoice_template("t1")
    assert got is not None and got.spec["vendor"] == "Electrica"

    database.update_invoice_template("t1", vendor="Electrica Muntenia")
    assert database.get_invoice_template("t1").vendor == "Electrica Muntenia"

    assert database.delete_invoice_template("t1") is not None
    assert database.get_invoice_template("t1") is None


def test_templates_scoped_by_project(database):
    database.create_invoice_template(InvoiceTemplate(id="a", vendor="A", spec=_spec("A"), projectId="p1", createdAt="x"))
    database.create_invoice_template(InvoiceTemplate(id="b", vendor="B", spec=_spec("B"), projectId=None, createdAt="x"))
    database.create_invoice_template(InvoiceTemplate(id="c", vendor="C", spec=_spec("C"), projectId="p2", createdAt="x"))
    ids = {t.id for t in database.list_invoice_templates(projectId="p1")}
    assert ids == {"a", "b"}  # p1 + shared, not p2
    assert {t.id for t in database.list_invoice_templates()} == {"a", "b", "c"}


# --- routes ----------------------------------------------------------

def test_create_template_validates_spec(client):
    bad = {"vendor": "X", "spec": {"vendor": "X", "match": ["m"], "fields": {"nope": {"after": "y"}}}}
    assert client.post("/invoice-templates", json=bad).status_code == 422

    ok = {"vendor": "Electrica", "spec": _spec()}
    r = client.post("/invoice-templates", json=ok)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] and body["createdAt"] and body["vendor"] == "Electrica"


def test_list_and_delete_template(client):
    tid = client.post("/invoice-templates", json={"vendor": "E", "spec": _spec()}).json()["id"]
    assert any(t["id"] == tid for t in client.get("/invoice-templates").json())
    assert client.delete(f"/invoice-templates/{tid}").status_code == 204
    assert all(t["id"] != tid for t in client.get("/invoice-templates").json())


def test_extract_needs_a_file_or_document_id(client):
    assert client.post("/invoices/extract", data={}).status_code == 422


def test_extract_image_falls_through_to_manual(client):
    files = {"file": ("scan.png", io.BytesIO(b"\x89PNG\r\n\x1a\n....."), "image/png")}
    body = client.post("/invoices/extract", files=files).json()
    assert body["source"] == "manual"
    assert set(body["needsReview"]) == {"vendor", "amount", "date"}


def test_extract_pdf_fixture_end_to_end(client):
    pdf = FIXTURES / "10335048078 (2) (3).pdf"
    if not pdf.exists():
        pytest.skip("raw sample PDF is gitignored / not present")
    files = {"file": (pdf.name, io.BytesIO(pdf.read_bytes()), "application/pdf")}
    body = client.post(
        "/invoices/extract",
        files=files,
        data={"names": "Vajda Stefan", "places": "Deva,Hunedoara"},
    ).json()
    assert body["templateVendor"] == "E.ON"
    assert body["parsed"]["amount"] == 176.09
    assert body["parsed"]["date"] == "2025-11-25"
    assert body["dueDate"] == "2025-12-10"
    assert body["needsReview"] == []


def test_extract_uses_a_saved_user_template(client):
    # a vendor the starter set doesn't know
    client.post("/invoice-templates", json={"vendor": "Salubritate SA", "spec": {
        "vendor": "Salubritate SA", "match": ["salubritate sa"],
        "category": "Utilities", "subcategory": "Trash",
        "fields": {"amount": {"after": "Total de plata", "kind": "money"}},
    }})
    # feed it a "document" via the store: create a link doc? no — needs a file.
    # exercise the text path directly through the helper the route uses.
    from api import _extract_from_text

    text = "SALUBRITATE SA\nFactura salubritate menajera\nTotal de plata 47,00 lei"
    res = _extract_from_text(text, names=[], places=[], project_id=None)
    assert res.templateVendor == "Salubritate SA"
    assert res.parsed["amount"] == 47.0
    assert res.parsed["subcategory"] == "Trash"
