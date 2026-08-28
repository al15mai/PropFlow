"""Provider selection + the run_text marshalling (task E5). No real browser."""
from __future__ import annotations

import pytest

from llm import providers


@pytest.fixture(autouse=True)
def _clean():
    providers.reset()
    yield
    providers.reset()


# --- config resolution ------------------------------------------------

def test_text_provider_default_and_override(monkeypatch):
    monkeypatch.delenv("AI_TEXT_PROVIDER", raising=False)
    assert providers.text_provider() == "gemini"
    monkeypatch.setenv("AI_TEXT_PROVIDER", "chatgpt")
    assert providers.text_provider() == "chatgpt"
    monkeypatch.setenv("AI_TEXT_PROVIDER", "nonsense")
    assert providers.text_provider() == "gemini"  # falls back


def test_feature_mode_default_and_override(monkeypatch):
    monkeypatch.delenv("AI_INVOICE_MODE", raising=False)
    assert providers.feature_mode("invoice") == "auto"
    monkeypatch.setenv("AI_INVOICE_MODE", "browser")
    assert providers.feature_mode("invoice") == "browser"
    monkeypatch.setenv("AI_MESSAGE_MODE", "api")
    assert providers.feature_mode("message") == "api"


def test_status_shape_without_a_browser():
    s = providers.status()
    assert set(s) >= {"playwrightInstalled", "textProvider", "invoiceMode",
                      "messageMode", "headless", "providers"}
    assert set(s["providers"]) == {"gemini", "chatgpt"}
    assert s["providers"]["gemini"] == {"clientBuilt": False, "ready": False}


# --- run_text marshalling with a fake client -------------------------

class _FakeClient:
    name = "fake"

    def __init__(self):
        self.calls = []

    def is_ready(self):
        return True

    def ask(self, prompt, **kw):
        self.calls.append(prompt)
        return f"echo: {prompt}"

    def close(self):
        pass


def test_run_text_passes_the_client_and_returns_result(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(providers, "_client_for", lambda p: fake)

    out = providers.run_text(lambda c: c.ask("hello"))
    assert out == "echo: hello"
    assert fake.calls == ["hello"]


def test_run_text_runs_on_a_worker_thread(monkeypatch):
    import threading

    fake = _FakeClient()
    monkeypatch.setattr(providers, "_client_for", lambda p: fake)
    tid = providers.run_text(lambda c: threading.get_ident())
    assert tid != threading.get_ident()


def test_run_text_propagates_client_errors(monkeypatch):
    from llm import LLMNotLoggedIn

    class _Broken(_FakeClient):
        def ask(self, prompt, **kw):
            raise LLMNotLoggedIn("no session")

    monkeypatch.setattr(providers, "_client_for", lambda p: _Broken())
    with pytest.raises(LLMNotLoggedIn):
        providers.run_text(lambda c: c.ask("x"))
