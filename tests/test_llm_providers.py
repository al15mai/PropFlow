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
        self.calls.append("__closed__")


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


def test_run_text_rebuilds_and_retries_once_when_the_client_wedges(monkeypatch):
    """A task that fails AND leaves the client unusable (page/browser dead):
    the cached client is closed + dropped and the task runs once more against a
    freshly built one. This is the fix for a single wedged session making every
    later request look permanently 'unavailable'."""
    from llm import LLMError

    built = []

    class _WedgingClient(_FakeClient):
        def __init__(self, healthy):
            super().__init__()
            self._healthy = healthy

        def is_ready(self):
            return self._healthy

        def ask(self, prompt, **kw):
            self.calls.append(prompt)
            if not self._healthy:
                raise LLMError("Gemini browser closed mid-task")
            return f"ok: {prompt}"

    def _fake_client_for(_p):
        # first build → wedged; second build (after drop) → healthy
        client = _WedgingClient(healthy=bool(built))
        built.append(client)
        return client

    monkeypatch.setattr(providers, "_client_for", _fake_client_for)

    out = providers.run_text(lambda c: c.ask("draft"))
    assert out == "ok: draft"
    assert len(built) == 2                      # rebuilt once
    assert "__closed__" in built[0].calls       # the wedged one was closed


def test_run_text_does_not_retry_when_the_client_is_still_healthy(monkeypatch):
    """A failure with a still-usable client (e.g. the model just didn't answer)
    is not a wedge — propagate it, no rebuild, no retry."""
    from llm import LLMError

    fake = _FakeClient()
    builds = []

    def _one_client(_p):
        builds.append(1)
        return fake

    def _boom(_c):
        raise LLMError("Gemini did not answer within the time budget")

    monkeypatch.setattr(providers, "_client_for", _one_client)
    with pytest.raises(LLMError):
        providers.run_text(_boom)
    assert len(builds) == 1                     # never rebuilt
    assert "__closed__" not in fake.calls


def test_shutdown_closes_each_client_on_its_worker(monkeypatch):
    fake = _FakeClient()
    # cache it the way the real _client_for would, and give it a worker
    providers._clients["gemini"] = fake
    providers._worker_for("gemini")
    assert "__closed__" not in fake.calls

    providers.shutdown()
    assert "__closed__" in fake.calls
    # caches cleared so the next call rebuilds cleanly
    assert providers.status()["providers"]["gemini"]["clientBuilt"] is False
