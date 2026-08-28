"""Shared browser-LLM plumbing (task E5): the client contract, the error
types the API layer turns into clean `ApiError`s, and the ordered-candidate
selector helpers ported from SongFlow (its DOM is a moving target, so every
selector is a list, never one hardcoded string).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path


class LLMError(Exception):
    """Base for every browser-LLM failure. The API layer maps these to a
    clean JSON error, never a 500 stack trace."""


class LLMNotLoggedIn(LLMError):
    """The persistent browser profile has no active session — the one-time
    VNC-over-SSH login (D6's `propflow_login_vnc.sh`) hasn't been done."""


class LLMRateLimited(LLMError):
    """The provider is throttling / asking to slow down."""


class LLMUnavailable(LLMError):
    """Playwright / Chromium isn't installed, or the browser won't launch."""


def profiles_dir() -> Path:
    """Persistent Chromium profiles live OUTSIDE the repo tree (like uploads /
    the DB — tasks E8b / D6). `$PROPFLOW_BROWSER_PROFILES` overrides; default
    `~/propflow-data/browser_profiles`."""
    d = Path(
        os.environ.get("PROPFLOW_BROWSER_PROFILES")
        or (Path.home() / "propflow-data" / "browser_profiles")
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def human_delay(min_s: float = 3.0, max_s: float = 9.0, long_chance: float = 0.06) -> None:
    """A randomised human-like pause before sending a prompt — a burst of
    scripted-looking prompts trips Gemini's "check your connection"
    automation defence (SongFlow's hard-won finding). Occasionally a longer
    pause so the cadence isn't perfectly bounded either."""
    if random.random() < long_chance:
        time.sleep(random.uniform(18.0, 40.0))
    else:
        time.sleep(random.uniform(min_s, max_s))


class BrowserLLM:
    """Contract every browser client implements. Subclasses own the DOM; this
    base only fixes the shape the provider layer + API routes rely on.

    All methods below MUST be called on the client's dedicated worker thread
    (see `llm.worker.LLMWorker`) — never from a request handler directly.
    """

    name: str = "browser-llm"

    def ensure_logged_in(self, timeout_s: int = 300) -> bool:
        """Open the browser/tab if needed and wait for the composer to appear.
        Fast no-op when a session is already active. Raises `LLMNotLoggedIn`
        on timeout."""
        raise NotImplementedError

    def is_ready(self) -> bool:
        """Cheap, non-raising check: is there a usable logged-in page right now?"""
        raise NotImplementedError

    def ask(self, prompt: str, *, image_png: bytes | None = None,
            timeout_s: float = 180.0) -> str:
        """Send one prompt (optionally with an image attached) and return the
        model's full text answer. Raises `LLMRateLimited` / `LLMError`."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


# Playwright wording when a call touches an already-closed page/context/browser
# — matched loosely, the phrasing has drifted across versions.
_CLOSED_PATTERNS = (
    "has been closed", "target closed", "browser has disconnected",
    "browser has been closed", "Connection closed",
)


def looks_like_closed_browser(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p.lower() in msg for p in _CLOSED_PATTERNS)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(raw: str):
    """Pull a single JSON object out of an LLM answer that may wrap it in prose
    or a ```json fence. Returns the dict, or None if nothing parses."""
    if not raw:
        return None
    candidates = [raw]
    m = _FENCE.search(raw)
    if m:
        candidates.insert(0, m.group(1))
    # also try from the first '{' to the last '}'
    lo, hi = raw.find("{"), raw.rfind("}")
    if 0 <= lo < hi:
        candidates.append(raw[lo : hi + 1])
    for c in candidates:
        try:
            val = json.loads(c.strip())
            if isinstance(val, dict):
                return val
        except (ValueError, TypeError):
            continue
    return None


def first_visible(page, selectors: list):
    """First selector in the ordered list that matches a visible element."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None
