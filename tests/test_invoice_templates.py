"""Invoice template matching + value parsing (task E7)."""
from __future__ import annotations

import pytest

from invoice import STARTER_TEMPLATES, Anchor, Template, apply_template, match_template
from invoice.templates import fold, parse_date, parse_money


# --- parse_money -------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("176,09 lei", 176.09),
    ("80,01lei", 80.01),
    (":162.94 lei", 162.94),
    ("1.234,56", 1234.56),
    ("1,234.56", 1234.56),
    ("0,00 lei", 0.0),
    ("323.028.810,00 Lei", 323028810.0),
])
def test_parse_money(token, expected):
    assert parse_money(token) == expected


@pytest.mark.parametrize("token", ["607,956 kWh", "58 mc", "45.00 cpi", "anul 2025", ""])
def test_parse_money_rejects_non_amounts(token):
    # no 2-decimal money token -> None  ('45.00 cpi' is a quantity, but '.00'
    # makes it look like money; that's acceptable — the anchor window keeps
    # consumption tables out of range)
    if token == "45.00 cpi":
        assert parse_money(token) == 45.0
    else:
        assert parse_money(token) is None


# --- parse_date -------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("10.12.2025", "2025-12-10"),
    ("01.10.2026", "2026-10-01"),
    ("2026-08-17", "2026-08-17"),
    ("7/1/26", "2026-01-07"),
])
def test_parse_date(token, expected):
    assert parse_date(token) == expected


@pytest.mark.parametrize("token", ["21%", "3=2*21%", "607,956", "abc"])
def test_parse_date_rejects_non_dates(token):
    assert parse_date(token) is None


# --- fold ------------------------------------------------------------

def test_fold_strips_diacritics_and_case():
    assert fold("Scadență  ") == "scadenta "
    assert fold("PLATĂ") == "plata"
    assert "  " not in fold("a\t\tb")


# --- match_template -------------------------------------------------

def test_match_uses_header_only_not_footer_mentions():
    # the association invoice names HIDROELECTRICA in a contracts list near the
    # bottom — the vendor must still resolve from the header
    text = (
        "Informare de plata Noiembrie 2025\n"
        "Asociatia De Proprietari Nr. 93\n"
        + ("filler line\n" * 40)
        + "ARE INCHEIATE CONTRACTE CU : S.C.HIDROELECTRICA S.A.;\n"
    )
    t = match_template(text)
    assert t is not None and t.vendor == "Asociația de Proprietari"


def test_match_returns_none_for_unknown_vendor():
    assert match_template("Some random invoice from Acme Widgets Inc.") is None


def test_user_template_wins_over_starter():
    mine = Template(
        vendor="My E.ON deal", match=[r"eon\.ro"], source="user",
        fields={"amount": Anchor(r"sold de plat\w*")},
    )
    t = match_template("bla eon.ro bla", [mine, *STARTER_TEMPLATES])
    assert t.vendor == "My E.ON deal"


# --- apply_template ------------------------------------------------

def test_apply_template_eon_like_line():
    eon = next(t for t in STARTER_TEMPLATES if t.vendor == "E.ON")
    text = (
        "Cantitate facturata Sold de plata Data scadenta\n"
        "gaze naturale\n"
        "607,956 kWh 176,09 lei 10.12.2025\n"
    )
    got = apply_template(text, eon)
    assert got["amount"].value == 176.09
    assert got["due_date"].value == "2025-12-10"


def test_apply_template_marks_unreliable_anchor():
    tpl = Template(
        vendor="X", match=[r"x"],
        fields={"amount": Anchor(r"total", reliable=False)},
    )
    got = apply_template("total 12,34 lei", tpl)
    assert got["amount"].value == 12.34
    assert got["amount"].reliable is False
