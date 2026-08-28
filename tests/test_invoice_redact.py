"""PII redaction for invoice text before it can reach an external LLM (task E7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from invoice import find_pii, redact

FIXTURES = Path(__file__).resolve().parents[2] / "services" / "__fixtures__" / "invoices"


# --- individual patterns -------------------------------------------------

def test_iban_removed():
    out = redact("IBAN: RO79BTRL02201205W18243XX plateste aici").text
    assert "RO79BTRL02201205W18243XX" not in out
    assert "plateste aici" in out


def test_email_and_phone_removed():
    out = redact("Scrie la clienti@hidroelectrica.ro sau 0800 070 444.").text
    assert "@" not in out
    assert "0800 070 444" not in out


def test_long_numbers_and_meter_codes_removed():
    src = "Cod client 1004573802 Numar factura 10335048078 CLC DEG0995749"
    out = redact(src).text
    assert "1004573802" not in out
    assert "10335048078" not in out
    assert "DEG0995749" not in out


def test_labelled_values_removed_but_labels_and_fields_kept():
    src = "Client: IOVAN IOAN\nData scadenta: 01.10.2026\nTotal de plata: 80,01 lei"
    out = redact(src).text
    assert "IOVAN IOAN" not in out
    # the anchor phrases and the money/date we extract must survive
    assert "Data scadenta" in out and "01.10.2026" in out
    assert "Total de plata" in out and "80,01 lei" in out


def test_scadenta_and_apa_are_not_mistaken_for_address_bits():
    # 'sc' / 'ap' as address abbreviations must not eat these words
    out = redact("Data scadenta 07.01.2026\nFactura apa 10.07 lei / m3").text
    assert "scadenta" in out
    assert "apa" in out
    assert "10.07" in out


def test_names_scrubbed_in_both_orders():
    out = redact("plata catre Vajda Stefan / STEFAN VAJDA", names=["Vajda Stefan"]).text
    assert "Vajda" not in out and "VAJDA" not in out
    assert "Stefan" not in out and "STEFAN" not in out


def test_extra_terms_scrubbed():
    out = redact("localitate Deva, judet Hunedoara", extra=[r"\bDeva\b", r"\bHunedoara\b"]).text
    assert "Deva" not in out and "Hunedoara" not in out


def test_amounts_and_consumption_are_preserved():
    src = "607,956 kWh 176,09 lei 10.12.2025\n58 mc\nTotal 1.234,56 lei"
    out = redact(src).text
    for keep in ("607,956", "176,09", "10.12.2025", "58 mc", "1.234,56"):
        assert keep in out


def test_control_and_private_use_glyphs_dropped():
    out = redact("A\x00BC (cid:128) D").text
    assert out.replace(" ", "") == "ABCD"


def test_counts_reported():
    r = redact("RO79BTRL02201205W18243XX x@y.ro 123456789012", names=[])
    assert r.counts.get("iban") == 1
    assert r.counts.get("email") == 1
    assert r.removed >= 3


# --- against the real (redacted) fixtures -------------------------------

_KNOWN_PII = [
    "VAJDA", "Vajda", "IOVAN", "Iovan", "Pescarilor", "BANPOTOC", "Banpotoc",
    "Deva", "Hunedoara", "DEG0995749", "RO63RNCB",
]


# the hard identifiers — these must never survive redaction. (phone/street/geo/
# unit can still fire on public helpline numbers or "[redacted]"-adjacent text.)
_HARD = {"iban", "email", "number", "code", "postal"}


@pytest.mark.parametrize("slug", ["eon-gas", "hidroelectrica-electricity", "asociatie-proprietari"])
def test_committed_fixture_has_no_known_pii(slug):
    p = FIXTURES / f"{slug}.text.txt"
    if not p.exists():
        pytest.skip(f"fixture {slug}.text.txt not generated")
    text = p.read_text(encoding="utf-8")
    for term in _KNOWN_PII:
        assert term not in text, f"{term!r} leaked into {slug}.text.txt"
    hard = [h for h in find_pii(text) if h.kind in _HARD]
    assert not hard, f"hard PII still in {slug}.text.txt: {hard[:3]}"
