"""Gemini (gemini.google.com/app) browser client (task E5).

A focused port of SongFlow's ``Automated_yt_web/gemini_client.py`` — kept:
the persistent-profile launch, the ordered-candidate selectors, the
login-wait, the clipboard-paste send, and the JS "read the last response
container, defend against nested duplicates" snapshot + stability polling.
Dropped (not needed by PropFlow): image generation, Google-account rotation,
and the per-stage usage telemetry.

Everything here must run on this client's dedicated worker thread
(``llm.worker.LLMWorker``) — Playwright's sync API pins objects to their
creating thread.
"""
from __future__ import annotations

import random
import time

from .base import (
    BrowserLLM,
    LLMError,
    LLMNotLoggedIn,
    LLMRateLimited,
    LLMUnavailable,
    first_visible,
    human_delay,
    looks_like_closed_browser,
    profiles_dir,
)

GEMINI_URL = "https://gemini.google.com/app"

PROMPT_INPUT_SELECTORS = [
    "div.ql-editor[contenteditable='true']",
    "rich-textarea div[contenteditable='true']",
    "div[aria-label*='prompt' i][contenteditable='true']",
    "div[role='textbox'][contenteditable='true']",
]
SEND_BUTTON_SELECTORS = [
    "button[aria-label*='Send' i]",
    "button.send-button",
    "button[data-test-id='send-button']",
]
# ordered candidates for the container holding one model text answer
RESPONSE_TEXT_SELECTORS = [
    "message-content",
    ".model-response-text",
    "model-response",
    ".response-container",
]
FILE_INPUT_SELECTORS = ["input[type='file']"]

POLL_INTERVAL_MS = 2000
STABLE_POLLS = 3

# Reads the LAST model-response container's text. Defends against a selector
# matching both an outer wrapper AND an inner content node (SongFlow saw this
# live for ChatGPT): keep only leaf matches, take the last.
_LAST_RESPONSE_JS = r"""
(selectors) => {
    for (const sel of selectors) {
        const all = Array.from(document.querySelectorAll(sel));
        if (all.length > 0) {
            const leaf = all.filter(n => !all.some(o => o !== n && n.contains(o)));
            const last = leaf[leaf.length - 1] || all[all.length - 1];
            return [sel, all.length, last.innerText || ""];
        }
    }
    return [null, 0, ""];
}
"""

_RATE_LIMIT_HINTS = (
    "you've reached your limit", "check your internet connection",
    "try again later", "rate limit", "prea multe cereri",
)


class GeminiClient(BrowserLLM):
    name = "gemini"

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._pw = None
        self._browser = None
        self.page = None
        self._profile = str(profiles_dir() / "gemini")

    # --- lifecycle ---------------------------------------------------------

    def _launch(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise LLMUnavailable("playwright is not installed (`uv sync`)") from e

        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch_persistent_context(
                user_data_dir=self._profile,
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 900},
                permissions=["clipboard-read", "clipboard-write"],
            )
        except Exception as e:
            raise LLMUnavailable(f"could not launch Chromium: {e}") from e

    def _open_page(self) -> None:
        self.page = self._browser.new_page()
        self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=90_000)

    def _ensure_browser(self) -> None:
        """Reopen the browser/tab if it was closed since the last task. Any
        failure confirming or reopening falls through to a full relaunch."""
        try:
            if self._browser is not None:
                _ = self._browser.pages  # raises once the context is closed
                if self.page is None or self.page.is_closed():
                    self._open_page()
                return
        except Exception:
            pass
        self._launch()
        self._open_page()

    def _logged_in(self) -> bool:
        """A visible composer on gemini.google.com — and NOT parked on a Google
        sign-in page. (The prompt input alone false-positives: the logged-out
        landing page also carries a contenteditable box.)"""
        try:
            url = self.page.url or ""
            if "accounts.google.com" in url or "/signin" in url:
                return False
            if "gemini.google.com" not in url:
                return False
            return first_visible(self.page, PROMPT_INPUT_SELECTORS) is not None
        except Exception:
            return False

    def ensure_logged_in(self, timeout_s: int = 300) -> bool:
        self._ensure_browser()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._logged_in():
                return True
            time.sleep(2)
        raise LLMNotLoggedIn(
            "Gemini composer never appeared — sign in once via the VNC-over-SSH "
            "flow (scripts/propflow_login_vnc.sh gemini)."
        )

    def is_ready(self) -> bool:
        return (
            self._browser is not None
            and self.page is not None
            and not self.page.is_closed()
            and self._logged_in()
        )

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self._browser = self.page = None

    # --- sending ---------------------------------------------------------

    def _snapshot(self):
        try:
            return self.page.evaluate(_LAST_RESPONSE_JS, RESPONSE_TEXT_SELECTORS)
        except Exception:
            return [None, 0, ""]

    def _attach_image(self, image_png: bytes) -> None:
        loc = first_visible(self.page, FILE_INPUT_SELECTORS) or self.page.locator(
            "input[type='file']"
        ).first
        loc.set_input_files(
            files=[{"name": "invoice.png", "mimeType": "image/png", "buffer": image_png}]
        )
        self.page.wait_for_timeout(1500)

    def _send(self, text: str) -> None:
        box = first_visible(self.page, PROMPT_INPUT_SELECTORS)
        if box is None:
            raise LLMError("Gemini prompt input not found")
        box.click()
        self.page.wait_for_timeout(random.randint(150, 500))
        try:
            self.page.evaluate(
                "async (t) => { await navigator.clipboard.writeText(t); }", text
            )
            self.page.keyboard.press("Control+V")
        except Exception:
            box.press_sequentially(text, delay=random.randint(20, 60))
        self.page.wait_for_timeout(random.randint(400, 1100))
        btn = first_visible(self.page, SEND_BUTTON_SELECTORS)
        if btn is not None and btn.is_enabled():
            btn.click()
        else:
            self.page.keyboard.press("Enter")

    def ask(self, prompt: str, *, image_png: bytes | None = None,
            timeout_s: float = 180.0) -> str:
        self.ensure_logged_in()
        try:
            _, before_count, before_text = self._snapshot()
            if image_png:
                self._attach_image(image_png)
            human_delay()
            self._send(prompt)

            deadline = time.time() + timeout_s
            stable_text, stable_hits = None, 0
            while time.time() < deadline:
                self.page.wait_for_timeout(POLL_INTERVAL_MS)
                sel, count, text = self._snapshot()
                grew = sel is not None and count > before_count
                changed = sel is not None and count == before_count and text != before_text
                if text.strip() and (grew or changed):
                    if text == stable_text:
                        stable_hits += 1
                        if stable_hits >= STABLE_POLLS:
                            return text.strip()
                    else:
                        stable_text, stable_hits = text, 1
                elif self._looks_rate_limited():
                    raise LLMRateLimited("Gemini appears rate-limited")
            raise LLMError("Gemini did not answer within the time budget")
        except (LLMError,):
            raise
        except Exception as e:
            if looks_like_closed_browser(e):
                raise LLMError("Gemini browser closed mid-task") from e
            raise LLMError(f"Gemini automation error: {e}") from e

    def _looks_rate_limited(self) -> bool:
        try:
            body = (self.page.inner_text("body") or "").lower()
        except Exception:
            return False
        return any(h in body for h in _RATE_LIMIT_HINTS)
