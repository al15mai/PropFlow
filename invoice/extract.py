"""Invoice extraction pipeline orchestrator (task E7).

Step 1 of the pipeline — deterministic, offline, instant:

    data (PDF bytes)  --pdf_to_text-->  text layer
    text              --extract-------> ExtractionResult (vendor / amount / date / …)

Steps 2-3 (multimodal model on the *redacted* text/image, then manual entry)
are wired later; :func:`invoice.redact.redact` is the gate for step 2 and
``ExtractionResult.needs_review`` tells the UI which fields to ask about.

Nothing here reads the DB or the stored files — the API layer owns that and
passes in the bytes plus any extra PII terms (tenant/owner names, property city).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .templates import STARTER_TEMPLATES, Template, apply_template, match_template

# maps a template subcategory to the app's ExpenseCategory (types.ts)
_CATEGORY = "Utilities"


@dataclass
class ExtractionResult:
    vendor: str | None = None
    amount: float | None = None
    date: str | None = None  # bill / issue date, ISO
    due_date: str | None = None  # ISO — not on ParsedInvoice, useful for alerts
    category: str = _CATEGORY
    subcategory: str | None = None
    description: str = ""
    template: str | None = None  # matched template vendor, or None
    needs_review: list = field(default_factory=list)  # field names low-confidence / missing
    source: str = "template"  # "template" | "model" | "manual"

    def to_parsed_invoice(self) -> dict:
        """Shape the frontend expects (``types.ts`` ``ParsedInvoice``)."""
        return {
            "vendor": self.vendor or "",
            "amount": self.amount if self.amount is not None else 0,
            "date": self.date or "",
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
        }


def pdf_to_text(data: bytes) -> str:
    """Extract the text layer of a PDF (all pages). Raises if pdfplumber is
    missing or the bytes aren't a PDF."""
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - env guard
        raise RuntimeError(
            "pdfplumber is required for PDF invoice extraction (`uv sync`)"
        ) from e

    import io

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


_REQUIRED = ("vendor", "amount", "date")


def extract(text: str, *, templates=None) -> ExtractionResult:
    """Run template matching + anchoring over an invoice's text layer.

    ``templates`` — user/auto templates to try before the built-in starter set
    (a match in this list wins). Pass ``None`` to use only the starter set.
    """
    all_templates = list(templates or []) + list(STARTER_TEMPLATES)
    tpl: Template | None = match_template(text, all_templates)

    res = ExtractionResult()
    if tpl is None:
        res.needs_review = list(_REQUIRED)
        return res

    res.vendor = tpl.vendor
    res.template = tpl.vendor
    res.category = tpl.category
    res.subcategory = tpl.subcategory

    got = apply_template(text, tpl)
    if "amount" in got:
        res.amount = got["amount"].value
        if not got["amount"].reliable:
            res.needs_review.append("amount")
    else:
        res.needs_review.append("amount")

    if "date" in got:
        res.date = got["date"].value
        if not got["date"].reliable:
            res.needs_review.append("date")
    else:
        res.needs_review.append("date")

    if "due_date" in got:
        res.due_date = got["due_date"].value

    bits = [tpl.vendor]
    if tpl.subcategory:
        bits.append(tpl.subcategory)
    res.description = " — ".join(bits)
    return res
