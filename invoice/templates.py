"""Per-vendor invoice templates + the value parsers (task E7).

A :class:`Template` says how to pull fields out of one issuer's invoice text:
which strings identify the vendor (matched against the **header** only — the
first few hundred characters — so a supplier merely *mentioned* further down
doesn't win), the expense category/subcategory to default, and an :class:`Anchor`
per field — a phrase to find, after which the first money / date token is the
value.

Text anchors only for v1. When flat-text order can't isolate a value the anchor
is marked ``reliable=False`` so :mod:`invoice.extract` flags it for review and
lets the model fallback fill it. Region-box anchors (``Anchor.region``) are a
later add for fixed-layout PDFs.

Users author their own templates in the app; those live in the ``invoice_templates``
DB table (wired after C6) and are passed to :func:`match_template` alongside
:data:`STARTER_TEMPLATES`. The starter set is tuned against the ``pdfplumber``
text layer of three real invoices (E.ON gas, Hidroelectrica electricity,
Asociație de Proprietari) — see ``services/__fixtures__/invoices/*.text.txt``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

IDENT_CHARS = 2500  # a vendor identifies itself well before this

# money must carry a decimal part — keeps consumption ("607,956 kWh"),
# quantities ("58 mc", "45.00 cpi") and years out. The thousands separator may
# be '.', ',' or a space; the decimal is the last '.'/','.
_MONEY = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+[.,]\d{2}(?!\d)|\d+[.,]\d{2}(?!\d)")
_DATE = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b"
)


def fold(s: str) -> str:
    """Lower-case, drop diacritics, squash inline whitespace. Matching only."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ș", "s").replace("ț", "t").replace("Ș", "s").replace("Ț", "t")
    s = re.sub(r"[ \t ]+", " ", s)
    return s.lower()


def parse_money(token: str):
    """'176,09 lei' -> 176.09 ; '1.234,56' -> 1234.56 ; ':162.94' -> 162.94."""
    m = _MONEY.search(token)
    if not m:
        return None
    raw = m.group(0)
    has_comma, has_dot = "," in raw, "." in raw
    if has_comma and has_dot:
        dec = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif has_comma:
        raw = raw.replace(",", ".") if len(raw.rsplit(",", 1)[-1]) == 2 else raw.replace(",", "")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        return round(float(raw.replace(" ", "")), 2)
    except ValueError:
        return None


def parse_date(token: str):
    """yyyy-mm-dd / dd.mm.yyyy / dd/mm/yy -> ISO 'YYYY-MM-DD' (RO day-first)."""
    m = _DATE.search(token)
    if not m:
        return None
    if m.group(1):
        y, mo, d = m.group(1), m.group(2), m.group(3)
    else:
        d, mo, y = m.group(4), m.group(5), m.group(6)
        if len(y) == 2:
            y = "20" + y
    try:
        mo_i, d_i = int(mo), int(d)
    except ValueError:
        return None
    if not (1 <= mo_i <= 12 and 1 <= d_i <= 31):
        return None
    return f"{int(y):04d}-{mo_i:02d}-{d_i:02d}"


@dataclass(frozen=True)
class Anchor:
    """Find ``after`` (regex, against folded text); the value is the first
    money/date token within ``window`` chars past the ``occurrence``-th match."""

    after: str
    kind: str = "money"  # "money" | "date"
    window: int = 160
    occurrence: int = 1
    reliable: bool = True
    region: object = None  # BBox for fixed-layout PDFs — later


@dataclass
class Template:
    vendor: str
    match: list  # regexes; any hit on the folded header identifies the vendor
    fields: dict  # name -> Anchor | list[Anchor] (first that yields a value wins)
    category: str = "Utilities"
    subcategory: object = None
    source: str = "builtin"  # "builtin" | "user" | "auto"

    def matches(self, folded_text: str) -> bool:
        return self.first_hit(folded_text) is not None

    def first_hit(self, folded_text: str):
        """Earliest start index of any identifying pattern, or ``None``."""
        hits = [m.start() for p in self.match for m in re.finditer(p, folded_text)]
        return min(hits) if hits else None


def match_template(text: str, templates=None):
    """Pick the template whose vendor marker appears **earliest** in the text.

    A supplier merely mentioned further down (e.g. "…contract cu HIDROELECTRICA"
    in an association invoice's footer) can't beat the issuer named in the header.
    """
    folded = fold(text[:IDENT_CHARS])
    best, best_pos = None, None
    for t in (STARTER_TEMPLATES if templates is None else templates):
        pos = t.first_hit(folded)
        if pos is not None and (best_pos is None or pos < best_pos):
            best, best_pos = t, pos
    return best


# --- (de)serialisation for user / auto templates (task E7, DB-backed) ---
#
# User templates are authored in the app. Their ``after`` / ``match`` values are
# treated as **literal phrases**, not regexes — we ``re.escape(fold(...))`` them.
# That removes any ReDoS surface from user input; the built-in starter templates
# keep full regex power because they are trusted code.

_MAX_MATCH = 8
_MAX_FIELDS = 8
_ALLOWED_FIELD_NAMES = {"amount", "date", "due_date", "account", "reference"}


class TemplateSpecError(ValueError):
    """A user-supplied template spec is malformed."""


def _literal(phrase: str) -> str:
    phrase = str(phrase).strip()
    if not phrase:
        raise TemplateSpecError("empty phrase")
    return re.escape(fold(phrase))


def anchor_from_spec(d: dict) -> Anchor:
    if not isinstance(d, dict) or "after" not in d:
        raise TemplateSpecError("anchor needs an 'after' phrase")
    kind = d.get("kind", "money")
    if kind not in ("money", "date"):
        raise TemplateSpecError(f"bad anchor kind {kind!r}")
    window = int(d.get("window", 160))
    occurrence = int(d.get("occurrence", 1))
    if not (10 <= window <= 2000) or not (1 <= occurrence <= 20):
        raise TemplateSpecError("anchor window/occurrence out of range")
    return Anchor(
        after=_literal(d["after"]), kind=kind, window=window,
        occurrence=occurrence, reliable=bool(d.get("reliable", True)),
    )


def template_from_spec(spec: dict, *, source: str = "user") -> Template:
    """Build a Template from the JSON the frontend / auto-detect stores.

    ``spec`` = {vendor, match: [phrase], category?, subcategory?,
                fields: {name: anchorSpec | [anchorSpec]}}
    """
    if not isinstance(spec, dict):
        raise TemplateSpecError("spec must be an object")
    vendor = str(spec.get("vendor", "")).strip()
    if not vendor:
        raise TemplateSpecError("template needs a vendor")

    match = spec.get("match") or []
    if not isinstance(match, list) or not match:
        raise TemplateSpecError("template needs at least one match phrase")
    if len(match) > _MAX_MATCH:
        raise TemplateSpecError("too many match phrases")
    match_patterns = [_literal(m) for m in match]

    raw_fields = spec.get("fields") or {}
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise TemplateSpecError("template needs at least one field")
    if len(raw_fields) > _MAX_FIELDS:
        raise TemplateSpecError("too many fields")
    fields: dict = {}
    for name, anchors in raw_fields.items():
        if name not in _ALLOWED_FIELD_NAMES:
            raise TemplateSpecError(f"unknown field {name!r}")
        seq = anchors if isinstance(anchors, list) else [anchors]
        fields[name] = [anchor_from_spec(a) for a in seq]

    return Template(
        vendor=vendor,
        match=match_patterns,
        fields=fields,
        category=str(spec.get("category") or "Utilities"),
        subcategory=(spec.get("subcategory") or None),
        source=source if source in ("user", "auto") else "user",
    )


@dataclass
class FieldResult:
    value: object
    reliable: bool
    anchor: object


def _extract_one(folded: str, anchor: Anchor):
    tokre = _MONEY if anchor.kind == "money" else _DATE
    parser = parse_money if anchor.kind == "money" else parse_date
    starts = [m.end() for m in re.finditer(anchor.after, folded)]
    if len(starts) < anchor.occurrence:
        return None
    pos = starts[anchor.occurrence - 1]
    tok = tokre.search(folded[pos : pos + anchor.window])
    if not tok:
        return None
    val = parser(tok.group(0))
    if val is None:
        return None
    return FieldResult(value=val, reliable=anchor.reliable, anchor=anchor.after)


def apply_template(text: str, template: Template) -> dict:
    """Run every field anchor. Missing fields are simply absent from the result."""
    folded = fold(text)
    out: dict = {}
    for name, spec in template.fields.items():
        for anchor in (spec if isinstance(spec, list) else [spec]):
            res = _extract_one(folded, anchor)
            if res is not None:
                out[name] = res
                break
    return out


# --- starter set -------------------------------------------------------

STARTER_TEMPLATES: list = [
    Template(
        vendor="E.ON",
        match=[r"\be\.?on\b", r"eon\.ro"],
        category="Utilities",
        subcategory="Gas",
        fields={
            "amount": [
                Anchor(r"sold de plat\w*"),
                Anchor(r"total valoare factur\w* curent\w*(?: cu tva)?"),
            ],
            # issue date sits on the "…factura curenta\n<amount> <date>" line
            "date": [Anchor(r"factur\w* curent\w*\s*\n", "date"), Anchor(r"dat\w* emitere", "date", occurrence=1, window=90)],
            "due_date": Anchor(r"dat\w* scaden\w*", "date"),
        },
    ),
    Template(
        vendor="Hidroelectrica",
        match=[r"hidroelectrica", r"\bspeeh\b"],
        category="Utilities",
        subcategory="Electricity",
        fields={
            "amount": Anchor(r"total de plat\w* factur\w* curent\w*"),
            "date": Anchor(r"din data de", "date"),
            "due_date": Anchor(r"data scaden\w*", "date"),
        },
    ),
    Template(
        vendor="Asociația de Proprietari",
        match=[r"asocia[tț]ia de proprietari", r"informare de plat"],
        category="Utilities",
        subcategory="Residents Association Tax",
        fields={
            "amount": [
                Anchor(r"total cheltuieli luna curent\w*\s*:?"),
                Anchor(r"total general\s*:?"),
            ],
            "date": Anchor(r"\bemitere\b\s*:?", "date"),
            "due_date": Anchor(r"scaden\w*\s*:?", "date"),
        },
    ),
]
