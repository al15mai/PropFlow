"""The dedicated-worker-thread primitive (task E5). No browser involved."""
from __future__ import annotations

import asyncio
import sys
import threading
import time

import pytest

from llm.worker import LLMWorker, _install_subprocess_capable_loop


def test_runs_func_and_returns_result():
    w = LLMWorker("t1")
    assert w.run(lambda: 2 + 40) == 42


def test_propagates_the_exception():
    w = LLMWorker("t2")
    with pytest.raises(ValueError, match="boom"):
        w.run(lambda: (_ for _ in ()).throw(ValueError("boom")))


def test_all_tasks_run_on_the_same_single_thread():
    w = LLMWorker("t3")
    seen = {w.run(threading.get_ident) for _ in range(5)}
    assert len(seen) == 1
    assert seen != {threading.get_ident()}  # ...and not the caller's thread


def test_tasks_are_serialised_not_interleaved():
    w = LLMWorker("t4")
    order: list = []

    def slow(tag):
        order.append(f"{tag}-start")
        time.sleep(0.05)
        order.append(f"{tag}-end")
        return tag

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(w.run, lambda: slow("A"))
        f2 = ex.submit(w.run, lambda: slow("B"))
        f1.result(); f2.result()

    # whichever ran first fully finished before the other started
    assert order in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    )


def test_wedged_task_times_out_and_worker_recovers():
    w = LLMWorker("t5")
    with pytest.raises(TimeoutError):
        w.run(lambda: time.sleep(5), timeout_s=0.2)
    # a fresh task still works (new thread + queue)
    assert w.run(lambda: "recovered") == "recovered"


def test_on_wedge_callback_fires():
    hits: list = []
    w = LLMWorker("t6", on_wedge=lambda: hits.append(1))
    with pytest.raises(TimeoutError):
        w.run(lambda: time.sleep(5), timeout_s=0.2)
    assert hits == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event-loop policy only")
def test_worker_thread_gets_a_subprocess_capable_loop_under_selector_policy(monkeypatch):
    """`uvicorn --reload` sets a process-wide WindowsSelectorEventLoopPolicy;
    a selector loop can't spawn Playwright's driver (bare NotImplementedError).
    The worker thread must end up on a Proactor loop regardless."""
    monkeypatch.setattr(
        asyncio, "get_event_loop_policy", lambda: asyncio.WindowsSelectorEventLoopPolicy()
    )
    w = LLMWorker("t7")

    def _probe():
        _install_subprocess_capable_loop()
        loop = asyncio.new_event_loop()
        try:
            return type(loop).__name__
        finally:
            loop.close()

    assert w.run(_probe) == "ProactorEventLoop"


def test_install_loop_helper_is_a_noop_off_windows(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("covered by the win32 test above")
    # must not raise on Linux/macOS
    _install_subprocess_capable_loop()
