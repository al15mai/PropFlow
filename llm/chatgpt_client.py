"""ChatGPT (chatgpt.com) browser client (task E5).

Same shape as ``gemini_client.GeminiClient`` — persistent profile, ordered
selectors, clipboard send, JS last-response snapshot + stability polling.

Live-DOM pass done 2026-08-29 against chatgpt.com:

- The composer is ``#prompt-textarea`` (a ``div.ProseMirror``, contenteditable);
  the Send button only exists *after* text is typed, so login detection keys on
  the composer alone, never the button.
- **Cloudflare Turnstile** ("verify you are human") fingerprints Playwright's
  bundled Chromium and loops forever, even headful + logged in. Fixed by
  ``base.launch_stealth_context`` — system Chrome (``channel="chrome"``) plus a
  ``navigator.webdriver`` spoof, which cleared it every time in testing. If a
  future Cloudflare update re-blocks, ``ensure_logged_in`` says so explicitly
  and the fix is a manual checkbox solve or ``AI_TEXT_PROVIDER=gemini``.

Gemini stays the primary provider (no Cloudflare, no Chrome dependency); ChatGPT
is the rate-limit backup. Never use ``Download.save_as()`` (it wedged SongFlow's
worker twice) — not that this client downloads anything.
"""
from __future__ import annotations

import random
import time

from .base import (
    STEALTH_INIT_JS,
    BrowserLLM,
    LLMError,
    LLMNotLoggedIn,
    LLMRateLimited,
    LLMUnavailable,
    first_visible,
    human_delay,
    launch_stealth_context,
    looks_like_closed_browser,
    looks_like_cloudflare_challenge,
    profiles_dir,
)

CHATGPT_URL = "https://chatgpt.com"

PROMPT_INPUT_SELECTORS = [
    "#prompt-textarea",
    "div#prompt-textarea[contenteditable='true']",
    "div[contenteditable='true'][data-id]",
    "textarea[data-id='root']",
    "div[role='textbox'][contenteditable='true']",
]
SEND_BUTTON_SELECTORS = [
    "button[data-testid='send-button']",
    "button[data-testid='composer-submit-button']",
    "button[aria-label*='Send' i]",
]
# ChatGPT swaps Send for Stop while streaming — an unambiguous "turn in flight"
STOP_BUTTON_SELECTORS = [
    "button[data-testid='stop-button']",
    "button[aria-label*='Stop' i]",
]
RESPONSE_TEXT_SELECTORS = [
    "[data-message-author-role='assistant'] .markdown",
    "[data-message-author-role='assistant']",
    ".agent-turn .markdown",
]
FILE_INPUT_SELECTORS = ["input[type='file']"]

POLL_INTERVAL_MS = 2000
STABLE_POLLS = 3

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
    "you've reached your", "rate limit", "please try again later",
    "too many requests", "usage limit",
)


class ChatGPTClient(BrowserLLM):
    name = "chatgpt"

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._pw = None
        self._browser = None
        self.page = None
        self._profile = str(profiles_dir() / "chatgpt")

    def _launch(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise LLMUnavailable("playwright is not installed (`uv sync`)") from e
        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            # system Chrome + navigator.webdriver spoof — clears Cloudflare
            # Turnstile on chatgpt.com (bundled Chromium never gets past it).
            self._browser = launch_stealth_context(
                self._pw,
                profile=self._profile,
                headless=self.headless,
                permissions=["clipboard-read", "clipboard-write"],
            )
            self._browser.add_init_script(STEALTH_INIT_JS)
        except Exception as e:
            raise LLMUnavailable(f"could not launch Chrome: {e}") from e

    def _open_page(self) -> None:
        self.page = self._browser.new_page()
        self.page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=90_000)

    def _ensure_browser(self) -> None:
        try:
            if self._browser is not None:
                _ = self._browser.pages
                if self.page is None or self.page.is_closed():
                    self._open_page()
                return
        except Exception:
            pass
        self._launch()
        self._open_page()

    def _logged_in(self) -> bool:
        try:
            url = self.page.url or ""
            if "auth.openai.com" in url or "/auth/login" in url:
                return False
            if "chatgpt.com" not in url and "chat.openai.com" not in url:
                return False
            if looks_like_cloudflare_challenge(self.page):
                return False
            return first_visible(self.page, PROMPT_INPUT_SELECTORS) is not None
        except Exception:
            return False

    def ensure_logged_in(self, timeout_s: int = 300) -> bool:
        self._ensure_browser()
        deadline = time.time() + timeout_s
        cf_seen = False
        while time.time() < deadline:
            if self._logged_in():
                return True
            if looks_like_cloudflare_challenge(self.page):
                cf_seen = True
            time.sleep(2)
        if cf_seen:
            raise LLMNotLoggedIn(
                "ChatGPT is stuck on Cloudflare's 'verify you are human' check — "
                "the stealth launch (system Chrome + webdriver spoof) didn't clear "
                "it. Solve the checkbox once in the visible window, or fall back to "
                "the Gemini provider (AI_TEXT_PROVIDER=gemini)."
            )
        raise LLMNotLoggedIn(
            "ChatGPT composer never appeared — sign in once via "
            "scripts/propflow_login_vnc.sh chatgpt."
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

    def _snapshot(self):
        try:
            return self.page.evaluate(_LAST_RESPONSE_JS, RESPONSE_TEXT_SELECTORS)
        except Exception:
            return [None, 0, ""]

    def _streaming(self) -> bool:
        return first_visible(self.page, STOP_BUTTON_SELECTORS) is not None

    def _attach_image(self, image_png: bytes) -> None:
        loc = self.page.locator("input[type='file']").first
        loc.set_input_files(
            files=[{"name": "invoice.png", "mimeType": "image/png", "buffer": image_png}]
        )
        self.page.wait_for_timeout(2000)

    def _send(self, text: str) -> None:
        box = first_visible(self.page, PROMPT_INPUT_SELECTORS)
        if box is None:
            raise LLMError("ChatGPT prompt input not found")
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
                if text.strip() and (grew or changed) and not self._streaming():
                    if text == stable_text:
                        stable_hits += 1
                        if stable_hits >= STABLE_POLLS:
                            return text.strip()
                    else:
                        stable_text, stable_hits = text, 1
                elif self._looks_rate_limited():
                    raise LLMRateLimited("ChatGPT appears rate-limited")
            raise LLMError("ChatGPT did not answer within the time budget")
        except LLMError:
            raise
        except Exception as e:
            if looks_like_closed_browser(e):
                raise LLMError("ChatGPT browser closed mid-task") from e
            raise LLMError(f"ChatGPT automation error: {e}") from e

    def _looks_rate_limited(self) -> bool:
        try:
            body = (self.page.inner_text("body") or "").lower()
        except Exception:
            return False
        return any(h in body for h in _RATE_LIMIT_HINTS)
