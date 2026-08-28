"""End-to-end invoice extraction over the sanitized fixtures (task E7).

The committed ``services/__fixtures__/invoices/<slug>.text.txt`` files are the
**redacted** text layer of three real invoices; ``<slug>.expected.json`` is the
contract. Regenerate with ``scripts/investigations/gen_invoice_fixtures.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice import extract

FIXTURES = Path(__file__).resolve().parents[2] / "services" / "__fixtures__" / "invoices"
SLUGS = ["eon-gas", "hidroelectrica-electricity", "asociatie-proprietari"]


def _load(slug):
    txt = FIXTURES / f"{slug}.text.txt"
    exp = FIXTURES / f"{slug}.expected.json"
    if not (txt.exists() and exp.exists()):
        pytest.skip(f"fixture {slug} not generated")
    return txt.read_text(encoding="utf-8"), json.loads(exp.read_text(encoding="utf-8"))["expected"]


@pytest.mark.parametrize("slug", SLUGS)
def test_fixture_extraction_matches_contract(slug):
    text, expected = _load(slug)
    res = extract(text)
    assert res.vendor == expected["vendor"]
    assert res.category == expected["category"]
    assert res.subcategory == expected["subcategory"]
    assert res.amount == expected["amount"]
    assert res.date == expected["date"]
    assert res.due_date == expected["due_date"]
    assert sorted(res.needs_review) == sorted(expected["needs_review"])


@pytest.mark.parametrize("slug", SLUGS)
def test_fixture_maps_to_parsed_invoice_shape(slug):
    text, expected = _load(slug)
    pi = extract(text).to_parsed_invoice()
    assert set(pi) == {"vendor", "amount", "date", "category", "subcategory", "description"}
    assert pi["amount"] == expected["amount"]
    assert pi["description"]


def test_unknown_vendor_flags_all_required_fields():
    res = extract("Invoice from Acme Widgets\nAmount 50.00\nDue 2026-01-01")
    assert res.vendor is None
    assert res.template is None
    assert set(res.needs_review) == {"vendor", "amount", "date"}
    assert res.to_parsed_invoice()["amount"] == 0


def test_pdf_to_text_reads_a_real_fixture_pdf():
    pdfplumber = pytest.importorskip("pdfplumber")  # noqa: F841
    pdfs = list(FIXTURES.glob("*.pdf"))
    if not pdfs:
        pytest.skip("raw PDFs are gitignored / not present")
    from invoice import pdf_to_text

    text = pdf_to_text(pdfs[0].read_bytes())
    assert len(text) > 200


def test_pdf_to_text_rejects_non_pdf():
    from invoice import pdf_to_text

    with pytest.raises(Exception):
        pdf_to_text(b"this is not a pdf")
