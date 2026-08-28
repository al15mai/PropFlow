"""Browser-driven LLM automation (task E5).

A backend capability: drive a persistent, logged-in Gemini / ChatGPT web
session via Playwright for text answers when the paid API isn't available
(no key, key degraded) — the fallback path for E7 invoice extraction and E6
message drafting.

  playwright_setup.ensure_playwright_ready()  — install Chromium on startup
  providers.run_text(func)                     — run func(client) on the
                                                 provider's dedicated thread
  providers.login(provider)                    — the VNC-login endpoint's work
  providers.status()                           — GET /ai/status snapshot

Nothing here touches the DB or the request thread; see each module.
"""
from __future__ import annotations

from .base import (
    BrowserLLM,
    LLMError,
    LLMNotLoggedIn,
    LLMRateLimited,
    LLMUnavailable,
)
from .playwright_setup import ensure_playwright_ready
from .providers import (
    feature_mode,
    login,
    reset,
    run_text,
    status,
    text_provider,
)
from .worker import LLMWorker

__all__ = [
    "BrowserLLM",
    "LLMError",
    "LLMNotLoggedIn",
    "LLMRateLimited",
    "LLMUnavailable",
    "LLMWorker",
    "ensure_playwright_ready",
    "feature_mode",
    "login",
    "reset",
    "run_text",
    "status",
    "text_provider",
]
