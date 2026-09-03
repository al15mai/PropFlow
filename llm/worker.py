"""One long-lived worker thread per browser (task E5).

Playwright's sync API pins a browser/page to the exact OS thread that created
it — they can never be driven from another thread afterward. FastAPI request
handlers run on a pool, so a browser created on request #1's thread would be
unusable (and orphaned) by request #2. The fix, ported from SongFlow's
``run_on_gemini_thread`` / ``run_on_chatgpt_thread``: **one worker thread we
create and keep alive for the process lifetime**; every Playwright call for a
given provider's shared client goes through that thread's queue. That also
serialises access, so text + image calls share one browser with no extra locks.

Each queued ``func`` should be a *complete task* (a whole extraction, a whole
message draft) — tasks are run whole, not interleaved.

On a per-task timeout the worker is assumed permanently wedged: its thread and
queue are abandoned (can't be touched from here) in favour of fresh ones, and
any browser process still holding the profile dir is force-killed by directory
match (can't go through Playwright either). The next task starts clean.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import queue
import subprocess
import sys
import threading
from typing import Callable


def _install_subprocess_capable_loop() -> None:
    """Give THIS thread an event loop that can spawn child processes.

    Playwright's sync API starts its Node driver with
    ``asyncio.create_subprocess_exec``. On Windows that needs a
    ``ProactorEventLoop`` — but ``uvicorn --reload`` calls
    ``asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())``
    process-wide (it spawns a file-watcher subprocess), and a **selector** loop
    raises a bare ``NotImplementedError`` the instant Playwright tries to
    launch its driver. That was the whole "AI unavailable / NotImplementedError"
    bug under ``--reload``.

    Playwright builds its loop with ``asyncio.new_event_loop()``, which asks the
    global *policy* — not this thread's current loop — so we both (a) create a
    Proactor loop and set it as this worker thread's loop, and (b) swap the
    global policy to the Proactor one. (b) is safe here: uvicorn's server
    subprocess (where our app runs) never spawns anything through asyncio; only
    the separate reloader parent process does, and it has its own interpreter.

    No-op off Windows."""
    if sys.platform != "win32":
        return
    proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if proactor_policy is None:  # pragma: no cover - very old Python
        return
    try:
        if not isinstance(asyncio.get_event_loop_policy(), proactor_policy):
            asyncio.set_event_loop_policy(proactor_policy())
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception as e:  # pragma: no cover - defensive
        print(f"[llm] could not install a Proactor event loop: {e}")

DEFAULT_TASK_TIMEOUT_S = 600.0


def kill_stale_profile_processes(profile_dir: str) -> None:
    """Best-effort force-kill of any browser process still holding
    ``profile_dir``'s singleton lock. Never raises."""
    try:
        if os.name == "nt":
            ps = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*{profile_dir}*' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=20,
            )
        else:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/cmdline", "rb") as f:
                        cmdline = f.read().decode(errors="ignore")
                except Exception:
                    continue
                if profile_dir and profile_dir in cmdline:
                    try:
                        os.kill(int(entry), 9)
                    except Exception:
                        pass
    except Exception as e:  # pragma: no cover - best effort
        print(f"[llm] could not clean stale browser processes: {e}")


class LLMWorker:
    """A single dedicated thread that runs submitted callables one at a time.

    ``on_wedge`` (optional) is called with no args after a task times out, once
    the thread/queue have been abandoned — the place to drop a cached client so
    the next task rebuilds it.
    """

    def __init__(self, name: str, *, profile_dir: str = "", on_wedge: Callable | None = None):
        self._name = name
        self._profile_dir = profile_dir
        self._on_wedge = on_wedge
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._queue: "queue.Queue" = queue.Queue()

    def _loop(self, work_queue: "queue.Queue") -> None:
        # This thread owns the browser for its whole life; give it a
        # subprocess-capable event loop once, before any Playwright call.
        _install_subprocess_capable_loop()
        while True:
            try:
                func, fut = work_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(func())
                except BaseException as e:  # noqa: BLE001 - propagate to caller
                    fut.set_exception(e)

    def run(self, func: Callable, *, timeout_s: float = DEFAULT_TASK_TIMEOUT_S):
        """Run ``func()`` on the worker thread and return its result (or raise
        its exception). Raises ``TimeoutError`` and resets the worker if the
        task exceeds ``timeout_s``."""
        with self._lock:
            work_queue = self._queue
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, args=(work_queue,),
                    name=f"llm-{self._name}", daemon=True,
                )
                self._thread.start()

        fut: concurrent.futures.Future = concurrent.futures.Future()
        work_queue.put((func, fut))
        try:
            return fut.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            with self._lock:
                if self._queue is work_queue:
                    print(
                        f"[llm] worker {self._name!r} wedged (task > {timeout_s}s) — "
                        "abandoning it, next task starts a fresh browser."
                    )
                    self._thread = None
                    self._queue = queue.Queue()
                    if self._profile_dir:
                        kill_stale_profile_processes(self._profile_dir)
                    if self._on_wedge is not None:
                        try:
                            self._on_wedge()
                        except Exception:
                            pass
            raise TimeoutError(
                f"{self._name} task did not finish within {timeout_s}s — "
                "the browser/worker has been reset."
            )
