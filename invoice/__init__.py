"""Invoice extraction (task E7).

Turn an uploaded utility invoice (PDF text layer, later an image) into a
pre-filled expense: vendor / amount / date / category / subcategory.

Pipeline (see ``extract.py``), each step fills what it can and the user always
confirms before anything is saved:

  1. ``templates`` — per-vendor text-anchor rules. Deterministic, offline, instant.
  2. multimodal model / browser-LLM fallback — on a **redacted** document only
     (``redact.py``; wired with E5).
  3. manual entry, pre-filled with whatever 1-2 produced.

Nothing in this package touches the DB or the live invoice files directly; the
API layer (``api.py``, wired after C6) owns storage and the ``invoice_templates``
table.
"""
from __future__ import annotations

from .extract import ExtractionResult, extract, pdf_to_text
from .redact import RedactionResult, find_pii, redact
from .templates import (
    Anchor,
    STARTER_TEMPLATES,
    Template,
    apply_template,
    match_template,
    parse_date,
    parse_money,
)

__all__ = [
    "ExtractionResult",
    "extract",
    "pdf_to_text",
    "RedactionResult",
    "find_pii",
    "redact",
    "Anchor",
    "Template",
    "STARTER_TEMPLATES",
    "apply_template",
    "match_template",
    "parse_date",
    "parse_money",
]
