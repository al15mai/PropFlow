"""Tests for the D5b self-update / restart engine in system_update.py.

`run_git_update` is exercised against throwaway local git repos (a bare "origin"
+ a working clone) in tmp dirs — no network, nothing touches the real repos.
`schedule_self_restart` is checked for its threading/exit contract without
actually calling `os._exit`.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

import system_update
from system_update import _lockfiles_changed, run_git_update


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not on PATH")


def _run(*args, cwd):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo_pair(tmp_path):
    """A bare 'origin' repo + a working clone tracking `main`, one commit deep."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    seed = tmp_path / "seed"

    _run("git", "init", "--bare", "-b", "main", str(origin), cwd=tmp_path)

    _run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    _run("git", "-C", str(seed), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(seed), "config", "user.name", "t", cwd=tmp_path)
    (seed / "app.txt").write_text("v1\n")
    (seed / "uv.lock").write_text("lock-v1\n")
    _run("git", "-C", str(seed), "add", "-A", cwd=tmp_path)
    _run("git", "-C", str(seed), "commit", "-m", "v1", cwd=tmp_path)
    _run("git", "-C", str(seed), "remote", "add", "origin", str(origin), cwd=tmp_path)
    _run("git", "-C", str(seed), "push", "origin", "main", cwd=tmp_path)

    _run("git", "clone", str(origin), str(work), cwd=tmp_path)
    _run("git", "-C", str(work), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(work), "config", "user.name", "t", cwd=tmp_path)

    return {"origin": origin, "work": work, "seed": seed}


def _push_new_commit(seed, origin, *, files: dict[str, str], msg: str) -> str:
    for name, content in files.items():
        (seed / name).write_text(content)
    _run("git", "-C", str(seed), "add", "-A", cwd=seed)
    _run("git", "-C", str(seed), "commit", "-m", msg, cwd=seed)
    _run("git", "-C", str(seed), "push", "origin", "main", cwd=seed)
    return _run("git", "-C", str(seed), "rev-parse", "HEAD", cwd=seed).stdout.strip()


def test_update_noop_when_already_current(repo_pair):
    res = run_git_update(repo_pair["work"], "main")
    assert res["status"] == "ok"
    assert res["changed"] is False
    assert res["previous_sha"] == res["new_sha"]


def test_update_fast_forwards_to_new_commit(repo_pair):
    new_sha = _push_new_commit(
        repo_pair["seed"], repo_pair["origin"], files={"app.txt": "v2\n"}, msg="v2"
    )
    res = run_git_update(repo_pair["work"], "main")
    assert res["status"] == "ok"
    assert res["changed"] is True
    assert res["new_sha"] == new_sha
    assert (repo_pair["work"] / "app.txt").read_text() == "v2\n"


def test_update_refuses_dirty_tree_and_changes_nothing(repo_pair):
    _push_new_commit(
        repo_pair["seed"], repo_pair["origin"], files={"app.txt": "v2\n"}, msg="v2"
    )
    before = _run(
        "git", "-C", str(repo_pair["work"]), "rev-parse", "HEAD", cwd=repo_pair["work"]
    ).stdout.strip()
    (repo_pair["work"] / "app.txt").write_text("local edit\n")

    res = run_git_update(repo_pair["work"], "main")
    assert res["status"] == "dirty"
    after = _run(
        "git", "-C", str(repo_pair["work"]), "rev-parse", "HEAD", cwd=repo_pair["work"]
    ).stdout.strip()
    assert after == before  # HEAD untouched
    assert (repo_pair["work"] / "app.txt").read_text() == "local edit\n"  # edit kept


def test_update_refuses_non_fast_forward(repo_pair):
    # Diverge the local branch: commit locally, then a different commit upstream.
    (repo_pair["work"] / "app.txt").write_text("local commit\n")
    _run("git", "-C", str(repo_pair["work"]), "add", "-A", cwd=repo_pair["work"])
    _run("git", "-C", str(repo_pair["work"]), "commit", "-m", "local", cwd=repo_pair["work"])
    _push_new_commit(
        repo_pair["seed"], repo_pair["origin"], files={"app.txt": "upstream\n"}, msg="upstream"
    )

    res = run_git_update(repo_pair["work"], "main")
    assert res["status"] == "not_fast_forward"


def test_update_error_on_bad_remote(tmp_path):
    _run("git", "init", "-b", "main", str(tmp_path / "lonely"), cwd=tmp_path)
    r = tmp_path / "lonely"
    _run("git", "-C", str(r), "config", "user.email", "t@t.t", cwd=tmp_path)
    _run("git", "-C", str(r), "config", "user.name", "t", cwd=tmp_path)
    (r / "f").write_text("x")
    _run("git", "-C", str(r), "add", "-A", cwd=tmp_path)
    _run("git", "-C", str(r), "commit", "-m", "c", cwd=tmp_path)

    res = run_git_update(r, "main")
    assert res["status"] == "error"


def test_lockfiles_changed_detects_uv_lock(repo_pair):
    old = _run(
        "git", "-C", str(repo_pair["work"]), "rev-parse", "HEAD", cwd=repo_pair["work"]
    ).stdout.strip()
    new = _push_new_commit(
        repo_pair["seed"], repo_pair["origin"], files={"uv.lock": "lock-v2\n"}, msg="bump lock"
    )
    # Fetch so both SHAs are known locally.
    _run("git", "-C", str(repo_pair["work"]), "fetch", "origin", "main", cwd=repo_pair["work"])
    assert _lockfiles_changed(repo_pair["work"], old, new) == ["uv.lock"]


def test_lockfiles_changed_empty_when_only_source_moved(repo_pair):
    old = _run(
        "git", "-C", str(repo_pair["work"]), "rev-parse", "HEAD", cwd=repo_pair["work"]
    ).stdout.strip()
    new = _push_new_commit(
        repo_pair["seed"], repo_pair["origin"], files={"app.txt": "v2\n"}, msg="src only"
    )
    _run("git", "-C", str(repo_pair["work"]), "fetch", "origin", "main", cwd=repo_pair["work"])
    assert _lockfiles_changed(repo_pair["work"], old, new) == []


def test_lockfiles_changed_same_sha_is_empty(repo_pair):
    sha = _run(
        "git", "-C", str(repo_pair["work"]), "rev-parse", "HEAD", cwd=repo_pair["work"]
    ).stdout.strip()
    assert _lockfiles_changed(repo_pair["work"], sha, sha) == []


def test_schedule_self_restart_does_not_exit_synchronously(monkeypatch):
    """The exit must be deferred to a daemon thread, never called inline."""
    calls: list[int] = []
    monkeypatch.setattr(system_update.os, "_exit", lambda code: calls.append(code))

    system_update.schedule_self_restart(delay_s=0.05)
    assert calls == []  # nothing yet
    import time

    time.sleep(0.3)
    assert calls == [0]  # fired on the thread


def test_run_update_hard_fails_on_dirty_backend(monkeypatch):
    """run_update returns {status: error, backend: {...}} (api.py maps to 409)."""
    monkeypatch.setattr(
        system_update, "run_git_update", lambda *a, **k: {"status": "dirty", "detail": "M x"}
    )
    restarts: list[int] = []
    monkeypatch.setattr(system_update, "schedule_self_restart", lambda *a, **k: restarts.append(1))

    res = system_update.run_update()
    assert res["status"] == "error"
    assert res["backend"]["status"] == "dirty"
    assert restarts == []  # never restarts on a hard failure


def test_run_update_up_to_date_does_not_restart(monkeypatch):
    monkeypatch.setattr(
        system_update,
        "run_git_update",
        lambda *a, **k: {
            "status": "ok",
            "previous_sha": "aaa",
            "new_sha": "aaa",
            "changed": False,
        },
    )
    monkeypatch.setattr(system_update, "_lockfiles_changed", lambda *a, **k: [])
    restarts: list[int] = []
    monkeypatch.setattr(system_update, "schedule_self_restart", lambda *a, **k: restarts.append(1))

    res = system_update.run_update()
    assert res["status"] == "up_to_date"
    assert restarts == []
    assert "restarting" not in res
    # backend didn't move → migrations aren't even looked at
    assert res["migrations"]["status"] == "skipped"


# --- D2m: migrations run before the restart on a backend update ---------------

def _backend_moved(monkeypatch):
    """Make run_git_update report the backend fast-forwarded, frontend current."""
    calls = {"n": 0}

    def fake(repo_dir, branch):
        calls["n"] += 1
        if calls["n"] == 1:  # backend
            return {"status": "ok", "previous_sha": "old", "new_sha": "new", "changed": True}
        return {"status": "ok", "previous_sha": "f", "new_sha": "f", "changed": False}

    monkeypatch.setattr(system_update, "run_git_update", fake)
    monkeypatch.setattr(system_update, "_lockfiles_changed", lambda *a, **k: [])


def test_run_update_runs_pending_migrations_then_restarts(monkeypatch):
    _backend_moved(monkeypatch)
    monkeypatch.setattr(
        system_update, "_run_pending_migrations",
        lambda: {"status": "ok", "applied": ["011_x"], "skipped_manual": [], "backup": "/b"},
    )
    restarts: list[int] = []
    monkeypatch.setattr(system_update, "schedule_self_restart", lambda *a, **k: restarts.append(1))

    res = system_update.run_update()
    assert res["status"] == "updated"
    assert res["migrations"]["applied"] == ["011_x"]
    assert res["restarting"] is True
    assert restarts == [1]


def test_run_update_holds_restart_when_a_migration_fails(monkeypatch):
    _backend_moved(monkeypatch)
    monkeypatch.setattr(
        system_update, "_run_pending_migrations",
        lambda: {"status": "error", "detail": "migration 011_x failed: boom", "failed": "011_x"},
    )
    restarts: list[int] = []
    monkeypatch.setattr(system_update, "schedule_self_restart", lambda *a, **k: restarts.append(1))

    res = system_update.run_update()
    assert res["status"] == "migration_failed"
    assert res["restarting"] is False
    assert restarts == []  # deliberately NOT restarted onto a schema-mismatched DB
    assert res["migrations"]["failed"] == "011_x"


def test_run_update_skips_migrations_when_only_frontend_moved(monkeypatch):
    calls = {"n": 0}

    def fake(repo_dir, branch):
        calls["n"] += 1
        if calls["n"] == 1:  # backend unchanged
            return {"status": "ok", "previous_sha": "b", "new_sha": "b", "changed": False}
        return {"status": "ok", "previous_sha": "old", "new_sha": "new", "changed": True}

    monkeypatch.setattr(system_update, "run_git_update", fake)
    monkeypatch.setattr(system_update, "_lockfiles_changed", lambda *a, **k: [])
    monkeypatch.setattr(system_update, "_build_frontend_if_served", lambda: {"status": "skipped"})
    called = []
    monkeypatch.setattr(system_update, "_run_pending_migrations", lambda: called.append(1) or {})
    monkeypatch.setattr(system_update, "schedule_self_restart", lambda *a, **k: None)

    res = system_update.run_update()
    assert called == []  # backend didn't move → no migration pass
    assert res["migrations"]["status"] == "skipped"
