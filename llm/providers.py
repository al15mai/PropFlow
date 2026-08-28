"""Provider selection + the process-wide singletons (task E5).

Config (env, later `landlordSettings`):

  AI_TEXT_PROVIDER   = gemini | chatgpt          (default gemini)
  AI_INVOICE_MODE    = api | browser | auto      (default auto)
  AI_MESSAGE_MODE    = api | browser | auto      (default auto)
  AI_HEADLESS        = true  -> headless browser  (local debugging only; the
                               VPS runs headful under xvfb, D6)

`auto` = try the paid API first, fall back to the browser client. The API
path lives on the frontend today (`services/geminiService.ts`); the browser
path is these clients. This module owns the browser side + the worker thread.

One `LLMWorker` per provider; one lazily-built client per provider, reused
for the process lifetime (SongFlow's `get_gemini_client` pattern). Every call
into a client goes through `run_text(func)`.
"""
from __future__ import annotations

import os
from typing import Callable

from .base import LLMError, env_float, profiles_dir
from .worker import LLMWorker

_VALID_PROVIDERS = ("gemini", "chatgpt")
_VALID_MODES = ("api", "browser", "auto")


def text_provider() -> str:
    p = (os.environ.get("AI_TEXT_PROVIDER") or "gemini").strip().lower()
    return p if p in _VALID_PROVIDERS else "gemini"


def feature_mode(feature: str) -> str:
    env = {"invoice": "AI_INVOICE_MODE", "message": "AI_MESSAGE_MODE"}.get(feature)
    m = (os.environ.get(env) or "auto").strip().lower() if env else "auto"
    return m if m in _VALID_MODES else "auto"


def _headless() -> bool:
    return (os.environ.get("AI_HEADLESS") or "").strip().lower() in ("1", "true", "yes", "on")


# --- singletons -------------------------------------------------------------

_clients: dict = {}
_workers: dict = {}


def _worker_for(provider: str) -> LLMWorker:
    if provider not in _workers:
        profile = str(profiles_dir() / provider)

        def _drop_client(p=provider):
            _clients.pop(p, None)

        _workers[provider] = LLMWorker(provider, profile_dir=profile, on_wedge=_drop_client)
    return _workers[provider]


def _client_for(provider: str):
    """Build (once) the client. MUST be called on that provider's worker thread."""
    if provider not in _clients:
        if provider == "gemini":
            from .gemini_client import GeminiClient

            _clients[provider] = GeminiClient(headless=_headless())
        elif provider == "chatgpt":
            from .chatgpt_client import ChatGPTClient

            _clients[provider] = ChatGPTClient(headless=_headless())
        else:  # pragma: no cover
            raise LLMError(f"unknown provider {provider!r}")
    return _clients[provider]


def run_text(func: Callable, *, provider: str | None = None, timeout_s: float | None = None):
    """Run ``func(client)`` on the text provider's dedicated worker thread.

    ``func`` gets the ready client and returns whatever the caller needs;
    it must be a whole task (one ask + parse), not a partial step.
    """
    provider = provider or text_provider()
    worker = _worker_for(provider)
    budget = timeout_s if timeout_s is not None else env_float("AI_TASK_TIMEOUT_S", 300.0)

    def _task():
        return func(_client_for(provider))

    return worker.run(_task, timeout_s=budget)


def login(provider: str, timeout_s: int = 300) -> dict:
    """Open the browser and wait for a logged-in composer — the endpoint the
    VNC-over-SSH flow (`scripts/propflow_login_vnc.sh`) calls."""
    provider = provider.strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise LLMError(f"unknown provider {provider!r}")

    def _task(client):
        client.ensure_logged_in(timeout_s=timeout_s)
        return {"provider": provider, "loggedIn": True}

    return run_text(_task, provider=provider, timeout_s=timeout_s + 30)


def status() -> dict:
    """Cheap snapshot for GET /ai/status — never launches a browser."""
    try:
        import playwright  # noqa: F401

        playwright_installed = True
    except ImportError:
        playwright_installed = False

    providers = {}
    for p in _VALID_PROVIDERS:
        client = _clients.get(p)
        providers[p] = {
            "clientBuilt": client is not None,
            "ready": bool(client and client.is_ready()),
        }
    return {
        "playwrightInstalled": playwright_installed,
        "textProvider": text_provider(),
        "invoiceMode": feature_mode("invoice"),
        "messageMode": feature_mode("message"),
        "headless": _headless(),
        "providers": providers,
    }


def reset() -> None:
    """Test hook — drop cached clients + workers."""
    for c in list(_clients.values()):
        try:
            c.close()
        except Exception:
            pass
    _clients.clear()
    _workers.clear()
