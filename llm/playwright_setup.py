"""Make sure Playwright's Chromium is installed before anything tries to launch
it (task E5). Ported from SongFlow's ``Automated_yt_web/playwright_setup.py``.

``playwright install`` is idempotent and fast once everything is present, so
this is cheap to call unconditionally on startup rather than trying to detect
staleness. It never raises — a missing browser is surfaced later as a clean
"AI unavailable" API error, not a startup crash.
"""
from __future__ import annotations

import platform
import subprocess
import sys

_INSTALL_TIMEOUT_S = 600


def _run_playwright_cli(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "playwright", *args],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=_INSTALL_TIMEOUT_S,
    )


def ensure_playwright_ready() -> bool:
    """Returns True if Chromium is (now) installed, False if it couldn't be."""
    try:
        _run_playwright_cli("install", "chromium")
        print("[playwright] Chromium ready")
    except Exception as e:
        detail = getattr(e, "stderr", None) or str(e)
        print(f"[playwright] WARNING: 'playwright install chromium' failed: {detail}")
        return False

    # install-deps (apt-get) is Linux-only and needs root. The systemd unit
    # (D6) runs as a non-root user, so this is expected to fail there until
    # someone runs the printed command once by hand. Never fatal.
    if platform.system() == "Linux":
        try:
            _run_playwright_cli("install-deps", "chromium")
            print("[playwright] OS dependencies ready")
        except Exception as e:
            detail = getattr(e, "stderr", None) or str(e)
            print(
                "[playwright] WARNING: 'playwright install-deps chromium' failed "
                f"(likely needs root): {detail}\n"
                f"  Fix once: sudo {sys.executable} -m playwright install-deps chromium"
            )
    return True
