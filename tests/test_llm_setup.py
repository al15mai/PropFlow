"""playwright_setup + base helpers (task E5)."""
from __future__ import annotations

import subprocess

from llm import base
from llm.playwright_setup import ensure_playwright_ready


def test_ensure_playwright_ready_is_non_fatal_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, "playwright", stderr="nope")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert ensure_playwright_ready() is False  # returns, doesn't raise


def test_profiles_dir_is_outside_the_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPFLOW_BROWSER_PROFILES", str(tmp_path / "profiles"))
    d = base.profiles_dir()
    assert d.exists()
    assert "PropFlow" not in str(d) or str(tmp_path) in str(d)


def test_looks_like_closed_browser():
    assert base.looks_like_closed_browser(Exception("Target page, context or browser has been closed"))
    assert not base.looks_like_closed_browser(Exception("some unrelated error"))


def test_human_delay_is_quick_when_patched(monkeypatch):
    slept = []
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(base.random, "random", lambda: 0.99)  # never the long pause
    base.human_delay(min_s=1, max_s=1)
    assert slept == [1]
