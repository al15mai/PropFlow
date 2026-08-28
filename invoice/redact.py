"""Strip PII from invoice text before it leaves the box (task E7).

**Hard rule:** no invoice content is sent to an external LLM (Gemini/ChatGPT,
API or the E5 browser path) without going through :func:`redact` first.

This works on the already-extracted **text layer** (see :mod:`invoice.extract`),
not the binary PDF. It removes:

  - control chars / Private-Use glyphs (barcode & logo fonts)
  - IBANs
  - long digit runs — client / contract / invoice / payment codes, barcodes
  - 6-digit postal codes
  - e-mail addresses and phone numbers
  - values after identifying labels ("Client", "Titular", "Proprietar",
    "Adresa", "Cod client", "Loc de consum", "CNP", "Serie", ...)
  - street lines ("Strada X", "Aleea Y", "Bd. Z"), "Bl./Ap./Sc./Et. <n>",
    and locality / county markers ("Loc. X", "jud. Y", "sect. N")
  - caller-supplied names / fragments (the app passes tenant + owner names, and
    any city / county it wants scrubbed)

It keeps everything an extractor needs: amounts, dates, currency, consumption
(kWh / mc / m3), the vendor name and the anchor phrases around the totals. It is
deliberately **over-eager** — a false positive costs the model a little context;
a false negative leaks a landlord's or tenant's data.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MASK = "[redacted]"

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.ASCII)
_PHONE = re.compile(r"(?<![\d/])(?:\+?40[\s.-]?|0)(?:\d[\s.-]?){8,9}\d(?![\d/])")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_POSTAL = re.compile(r"(?<!\d)\d{6}(?!\d)")
# alphanumeric meter / connection-point / installation codes: DEG0995749,
# POD RO005E..., installation ids — letters then >=4 digits then optional tail
_CODE = re.compile(r"\b[A-Z]{2,}\d{4,}[A-Z0-9]*\b")

# "Label: value" — value redacted to end of line. Deliberately excludes
# "Data" and "Factura" (they carry the fields we want).
_LABELS = (
    r"client(?:ul)?", r"titular(?:ul)?", r"proprietar(?:ul)?", r"chiria[șs](?:ul)?",
    r"c[aă]tre", r"nume(?:le)?", r"name", r"adres[aă]", r"address", r"domiciliu",
    r"apartament(?:ul)?", r"loc(?:ul)? de consum", r"punct de consum",
    r"cod (?:client|[îi]?ncasare|incasare|abonat|loc consum|nlc)",
    r"cod cont contract", r"cod contract", r"cont contract",
    r"num[aă]r contract", r"nr\.? contract", r"serie(?:a)?(?: [șs]i num[aă]r)?",
    r"cnp", r"c\.?i\.?f\.?", r"c\.?u\.?i\.?", r"clc", r"tel(?:efon)?(?:\.\w+)?",
    r"cod punct de m[aă]sur[aă][^:]*", r"punct de m[aă]sur[aă][^:]*",
    r"consiliul (?:director|de administra[țt]ie)", r"consiliu de administra[țt]ie",
    r"administrator", r"pre[șs]edinte", r"director(?: general)?(?: adj\.?)?",
)
_LABEL_VALUE = re.compile(
    r"^(\s*(?:%s)\s*[:#-]?[ \t]*)(\S.*)$" % "|".join(_LABELS),
    re.IGNORECASE | re.MULTILINE,
)

_STREET = re.compile(
    r"\b(?:strada|str\.|bd\.|b-?dul|bulevardul|aleea|calea|[șs]oseaua|"
    r"splaiul|intrarea|pia[țt]a|drumul)\s+[^\n,]+",
    re.IGNORECASE,
)
# REQUIRE a period or the spelled-out word, so "scadență"/"apă"/"structură" survive
_UNIT = re.compile(
    r"\b(?:bl|ap|sc|et)\.\s*[\w./-]{1,6}\b"
    r"|\b(?:bloc|scara|apartament(?:ul)?|etaj(?:ul)?)\s+[\w./-]{1,6}\b",
    re.IGNORECASE,
)
# "Loc. BANPOTOC", "Judeţul Hunedoara", "localitate Deva", "sect. 1", "com. X" —
# marker is case-insensitive, the value must start with a capital (a place name).
# Bare "City, County" with no marker is a known residual — the API layer passes
# the property's city/county via ``extra`` for defence in depth.
_GEO = re.compile(
    r"(?i:\b(?:loc(?:alitate[a]?)?|jude?[țt]?(?:ul)?|sect(?:or)?|com(?:una)?"
    r"|mun(?:icipiul)?|sat|ora[șs](?:ul)?)\b)\.?/?\s*(?i:sect\.?)?\s*"
    r"[A-ZȘȚĂÎÂ][A-Za-zĂÂÎȘȚăâîșț.-]+(?:\s+[A-ZȘȚĂÎÂ][A-Za-zĂÂÎȘȚăâîșț.-]+){0,2}"
)


def _drop_nonprintable(s: str) -> str:
    """Strip control chars and Private-Use glyphs that make text read as binary."""
    return "".join(
        ch for ch in s if ch in "\t\n" or unicodedata.category(ch)[0] != "C"
    )


@dataclass
class RedactionResult:
    text: str
    counts: dict = field(default_factory=dict)

    @property
    def removed(self) -> int:
        return sum(self.counts.values())


def _name_variants(name: str) -> list:
    name = " ".join(name.split())
    if len(name) < 3:
        return []
    parts = name.split(" ")
    variants = {name, name.upper(), " ".join(parts[::-1]), " ".join(parts[::-1]).upper()}
    return [re.escape(v) for v in variants if len(v) > 2]


def redact(text: str, *, names=(), extra=()) -> RedactionResult:
    """Return *text* with PII masked.

    ``names``  — person names to scrub ("First Last" and "Last First", case-insensitive).
    ``extra``  — extra regex strings to scrub verbatim (cities, counties, …).
    """
    counts: dict = {}

    def sub(pattern, repl, s, kind):
        rx = re.compile(pattern) if isinstance(pattern, str) else pattern
        s2, n = rx.subn(repl, s)
        if n:
            counts[kind] = counts.get(kind, 0) + n
        return s2

    text = _drop_nonprintable(text)
    text = re.sub(r"\(cid:\d+\)", "", text)  # pdfplumber's unmapped-glyph marker

    for pat in extra or ():
        text = sub(pat, MASK, text, "extra")
    for name in names or ():
        for variant in _name_variants(str(name)):
            text = sub(re.compile(variant, re.IGNORECASE), MASK, text, "name")

    text = sub(_LABEL_VALUE, lambda m: m.group(1) + MASK, text, "label")
    text = sub(_STREET, MASK, text, "street")
    text = sub(_GEO, MASK, text, "geo")
    text = sub(_UNIT, MASK, text, "unit")
    text = sub(_IBAN, MASK, text, "iban")
    text = sub(_EMAIL, MASK, text, "email")
    text = sub(_PHONE, MASK, text, "phone")
    text = sub(_CODE, MASK, text, "code")
    text = sub(_LONG_NUMBER, MASK, text, "number")
    text = sub(_POSTAL, MASK, text, "postal")

    text = re.sub(r"(?:\[redacted\][\s,;/-]*){2,}", MASK + " ", text)
    return RedactionResult(text=text, counts=counts)


@dataclass
class PiiHit:
    kind: str
    value: str
    start: int
    end: int


def find_pii(text: str) -> list:
    """Locate (don't remove) PII — for tests and a debug view."""
    text = re.sub(r"\(cid:\d+\)", "", _drop_nonprintable(text))
    hits = []
    for kind, rx in (
        ("iban", _IBAN), ("email", _EMAIL), ("phone", _PHONE), ("code", _CODE),
        ("number", _LONG_NUMBER), ("postal", _POSTAL),
        ("street", _STREET), ("geo", _GEO), ("unit", _UNIT),
    ):
        hits += [PiiHit(kind, m.group(0), m.start(), m.end()) for m in rx.finditer(text)]
    for m in _LABEL_VALUE.finditer(text):
        hits.append(PiiHit("label", m.group(2).strip(), m.start(2), m.end(2)))
    hits.sort(key=lambda h: h.start)
    return hits
