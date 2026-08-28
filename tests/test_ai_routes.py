"""The /ai/* routes + the invoice model fallback (task E5). No real browser —
`llm.providers.run_text` is monkeypatched throughout.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from llm import LLMNotLoggedIn, providers

FIXTURES = Path(__file__).resolve().parents[2] / "services" / "__fixtures__" / "invoices"


@pytest.fixture(autouse=True)
def _reset_providers():
    providers.reset()
    yield
    providers.reset()


def _fake_answer(text):
    """Make run_text(func) call func with a stub client that returns `text`."""
    class _Stub:
        name = "stub"
        def is_ready(self): return True
        def ask(self, prompt, **kw): return text
        def close(self): pass
    return lambda func, **kw: func(_Stub())


# --- /ai/status & /ai/login --------------------------------------------

def test_ai_status_shape(client):
    body = client.get("/ai/status").json()
    assert body["textProvider"] == "gemini"
    assert set(body["providers"]) == {"gemini", "chatgpt"}


def test_ai_login_maps_not_logged_in_to_503(client, monkeypatch):
    def _boom(provider, timeout_s=300):
        raise LLMNotLoggedIn("no session")
    monkeypatch.setattr(providers, "login", _boom)
    r = client.post("/ai/login", data={"provider": "gemini"})
    assert r.status_code == 503
    assert r.json()["detail"] == "ai_not_logged_in"


def test_ai_login_success(client, monkeypatch):
    monkeypatch.setattr(providers, "login", lambda p, timeout_s=300: {"provider": p, "loggedIn": True})
    r = client.post("/ai/login", data={"provider": "gemini"})
    assert r.status_code == 200 and r.json()["loggedIn"] is True


# --- /ai/message -------------------------------------------------------

def test_ai_message_requires_prompt(client):
    assert client.post("/ai/message", json={}).status_code == 422


def test_ai_message_returns_text(client, monkeypatch):
    monkeypatch.setattr(providers, "run_text", _fake_answer("Bună ziua, vă rugăm achitați chiria."))
    r = client.post("/ai/message", json={"prompt": "draft a late-rent reminder in Romanian"})
    assert r.status_code == 200
    assert "chiria" in r.json()["text"]


def test_ai_message_rate_limited_is_503(client, monkeypatch):
    from llm import LLMRateLimited
    def _rl(func, **kw):
        raise LLMRateLimited("slow down")
    monkeypatch.setattr(providers, "run_text", _rl)
    r = client.post("/ai/message", json={"prompt": "x"})
    assert r.status_code == 503 and r.json()["detail"] == "ai_rate_limited"


# --- /ai/extract-invoice + the /invoices/extract fallback -------------

_MODEL_JSON = (
    '```json\n{"vendor": "Digi", "amount": 55.0, "date": "2026-02-01", '
    '"dueDate": "2026-02-15", "category": "Utilities", "subcategory": "Internet"}\n```'
)


def test_ai_extract_invoice_forces_the_model_path(client, monkeypatch):
    monkeypatch.setattr(providers, "run_text", _fake_answer(_MODEL_JSON))
    pdf = FIXTURES / "10335048078 (2) (3).pdf"
    if not pdf.exists():
        pytest.skip("raw sample PDF gitignored")
    files = {"file": (pdf.name, io.BytesIO(pdf.read_bytes()), "application/pdf")}
    body = client.post("/ai/extract-invoice", files=files, data={"names": "Vajda Stefan"}).json()
    assert body["parsed"]["vendor"] == "Digi"
    assert body["parsed"]["amount"] == 55.0
    assert body["dueDate"] == "2026-02-15"
    assert body["source"] == "model"


def test_merge_extraction_fills_template_gaps_from_the_model():
    """The `_merge_extraction` helper: template result + model fields."""
    from api import _merge_extraction
    from invoice import extract

    # template gets vendor + amount + subcategory; date is missing
    res = extract(
        "ENGIE Romania\nSold de plata 120,50 lei\ngaze naturale",
        templates=None,
    )
    assert "date" in res.needs_review  # template couldn't date it

    merged = _merge_extraction(res, {"date": "2026-04-01", "dueDate": "2026-04-20"},
                               source="template")
    assert merged.parsed["date"] == "2026-04-01"
    assert merged.dueDate == "2026-04-20"
    assert merged.source == "template+model"
    assert "date" not in merged.needsReview


def test_merge_extraction_keeps_template_values_over_the_model():
    from api import _merge_extraction
    from invoice import extract

    res = extract(
        "E.ON ACTUAL GAS\nSold de plata 176,09 lei\nData scadenta 10.12.2025\n"
        "Data emitere 25.11.2025",
        templates=None,
    )
    # model disagrees on amount — template wins, model only fills gaps
    merged = _merge_extraction(res, {"amount": 999.0}, source="template")
    assert merged.parsed["amount"] == 176.09
