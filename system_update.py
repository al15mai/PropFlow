"""Git version introspection + self-update / restart engine.

`D5` part 1 shipped the read-only half (`get_git_status`, `GET /admin/version`).
`D5b` adds the write side — restart and update-and-restart, owner-only — modelled
on SongFlow's `Automated_yt_web/system_update.py`.

"Restart" here means **exit this process**. In production the `D6` systemd unit
(`propflow-api.service`, `Restart=always`) brings it straight back up on the code
just pulled; there is no local-supervisor detour (`main.py` stays a plain dev
launcher — a local `/admin/restart` just stops the API and `main.py` tears down
the paired Vite server, which is fine for dev).

The two repos are nested — `PropFlowUI` (frontend, parent) contains `PropFlow/`
(backend, child) — and update on separate branches:

  - backend  (`PropFlow/`)   tracks `origin/v0.0.2`  ($PROPFLOW_UPDATE_BRANCH)
  - frontend (`PropFlowUI/`)  tracks `origin/main`    ($PROPFLOW_UPDATE_BRANCH_FRONTEND)

`run_git_update` fetches, refuses to touch a dirty tree (aborts, changes nothing),
and only ever fast-forwards — it can never discard local work. If a fast-forward
would pull a changed `uv.lock` / `package-lock.json`, the matching install
(`uv sync` / `npm ci` + `npm run build`) runs before the restart.

Everything degrades gracefully: missing `git`, not-a-repo, or a failed command
leaves each field empty-ish and `available=False` — the version endpoint never
raises.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

# The backend repo (PropFlow/) is this file's own directory; the frontend repo
# is its parent.
BACKEND_REPO_DIR = Path(__file__).resolve().parent
FRONTEND_REPO_DIR = BACKEND_REPO_DIR.parent

# Branch each repo's prod checkout is meant to track. Overridable so a machine on
# a different branch (or a future rename) doesn't need a code change.
BACKEND_BRANCH = os.environ.get("PROPFLOW_UPDATE_BRANCH", "v0.0.2")
FRONTEND_BRANCH = os.environ.get("PROPFLOW_UPDATE_BRANCH_FRONTEND", "main")

# Lockfiles whose movement across an update range forces a dependency install
# before the restart. Path is relative to the repo root; `installer` is run with
# cwd set to that root.
_LOCKFILE_INSTALLS = {
    "uv.lock": ["uv", "sync", "--frozen", "--native-tls"],
    "package-lock.json": ["npm", "ci", "--silent"],
}


def _git(repo_dir: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        # Synthesise a failed CompletedProcess so callers can treat it uniformly.
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr=str(e))


def _git_out(repo_dir: Path, *args: str) -> str:
    proc = _git(repo_dir, *args, timeout=10)
    return proc.stdout.strip() if proc.returncode == 0 else ""


# --- version display (D5 part 1) ----------------------------------------------

def get_git_status(repo_dir: Path | str = BACKEND_REPO_DIR) -> Dict[str, Any]:
    """Commit / branch / tag / dirty state of ``repo_dir`` for the version card."""
    repo_dir = Path(repo_dir)

    sha = _git_out(repo_dir, "rev-parse", "HEAD")
    branch = _git_out(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")  # "HEAD" when detached
    tags = _git_out(repo_dir, "tag", "--points-at", "HEAD")
    log_line = _git_out(repo_dir, "log", "-1", "--format=%cI%x09%s")
    commit_date, _, commit_message = log_line.partition("\t")

    return {
        "sha": sha,
        "short_sha": sha[:7],
        "branch": branch,
        "tag": tags.splitlines()[0] if tags else "",
        "dirty": bool(_git_out(repo_dir, "status", "--porcelain")),
        "commit_date": commit_date,
        "commit_message": commit_message,
        "available": bool(sha),
    }


# --- update engine (D5b) ----------------------------------------------------

def _lockfiles_changed(repo_dir: Path, old_sha: str, new_sha: str) -> list[str]:
    """Which tracked lockfiles differ between two commits (empty if none / on error)."""
    if not old_sha or not new_sha or old_sha == new_sha:
        return []
    proc = _git(repo_dir, "diff", "--name-only", old_sha, new_sha)
    if proc.returncode != 0:
        return []
    changed = set(proc.stdout.split())
    return [name for name in _LOCKFILE_INSTALLS if name in changed]


def _run_install(repo_dir: Path, cmd: list[str]) -> Dict[str, Any]:
    """Run one dependency-install command in ``repo_dir``. Never raises."""
    exe = shutil.which(cmd[0])
    if not exe:
        return {"cmd": " ".join(cmd), "status": "skipped", "detail": f"{cmd[0]} not on PATH"}
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]], cwd=str(repo_dir), capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"cmd": " ".join(cmd), "status": "error", "detail": str(e)}
    if proc.returncode != 0:
        return {
            "cmd": " ".join(cmd),
            "status": "error",
            "detail": (proc.stderr.strip() or proc.stdout.strip())[-500:],
        }
    return {"cmd": " ".join(cmd), "status": "ok"}


def run_git_update(repo_dir: Path | str, branch: str) -> Dict[str, Any]:
    """Fetch + fast-forward-only update of ``repo_dir`` to ``origin/<branch>``.

    Never discards local changes — aborts with status ``"dirty"`` instead.
    Returns a dict always containing ``status``
    (``ok`` | ``dirty`` | ``not_fast_forward`` | ``error``), plus ``detail`` on
    non-ok, plus ``previous_sha`` / ``new_sha`` / ``changed`` (bool) on ok.
    """
    repo_dir = Path(repo_dir)
    previous_sha = _git_out(repo_dir, "rev-parse", "HEAD")

    fetch = _git(repo_dir, "fetch", "origin", branch)
    if fetch.returncode != 0:
        return {"status": "error", "detail": fetch.stderr.strip() or fetch.stdout.strip()}

    dirty = _git_out(repo_dir, "status", "--porcelain")
    if dirty:
        return {"status": "dirty", "detail": dirty}

    # Only ever move to a checked-out local branch that matches the target; if the
    # checkout is detached or on another branch, `checkout <branch>` still does
    # the right thing (fast-forwardable local branch or a fresh tracking one).
    checkout = _git(repo_dir, "checkout", branch)
    if checkout.returncode != 0:
        return {"status": "error", "detail": checkout.stderr.strip() or checkout.stdout.strip()}

    merge = _git(repo_dir, "merge", "--ff-only", f"origin/{branch}")
    if merge.returncode != 0:
        return {"status": "not_fast_forward", "detail": merge.stderr.strip() or merge.stdout.strip()}

    new_sha = _git_out(repo_dir, "rev-parse", "HEAD")
    return {
        "status": "ok",
        "previous_sha": previous_sha,
        "new_sha": new_sha,
        "changed": new_sha != previous_sha,
    }


def _build_frontend_if_served() -> Dict[str, Any]:
    """Rebuild the static bundle FastAPI serves (`$PROPFLOW_DIST`, task D6).

    Only meaningful in prod, where the frontend is a built `dist/` — in local dev
    Vite serves from source and there is nothing to build. No-ops (status
    ``"skipped"``) when `$PROPFLOW_DIST` is unset or npm is missing.
    """
    dist = os.environ.get("PROPFLOW_DIST")
    if not dist:
        return {"status": "skipped", "detail": "$PROPFLOW_DIST unset (dev — Vite serves source)"}
    npm = shutil.which("npm")
    if not npm:
        return {"status": "skipped", "detail": "npm not on PATH"}
    try:
        proc = subprocess.run(
            [npm, "run", "build"],
            cwd=str(FRONTEND_REPO_DIR),
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "VITE_API_BASE_URL": ""},
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "error", "detail": str(e)}
    if proc.returncode != 0:
        return {"status": "error", "detail": (proc.stderr.strip() or proc.stdout.strip())[-500:]}
    return {"status": "ok"}


def run_update(*, restart: bool = True) -> Dict[str, Any]:
    """Update both repos to their tracked branches and (optionally) restart.

    - Backend and frontend are fetched + fast-forwarded independently. A dirty or
      non-fast-forwardable **backend** tree fails the whole thing with 409-shaped
      detail (nothing was changed). The **frontend** is best-effort: a dirty /
      diverged frontend is reported under ``frontend`` but doesn't block a
      backend update (the repos move on separate schedules).
    - If a repo's fast-forward range changed its lockfile, the matching install
      runs (`uv sync` for the backend, `npm ci` for the frontend). If the
      frontend moved at all and a built bundle is being served, `npm run build`
      runs too.
    - Restarts (``schedule_self_restart``) only if something actually changed.

    Returns ``{status, backend, frontend, installs, restarting}``.
    ``status`` is ``updated`` | ``up_to_date``; raises nothing here — the caller
    (api.py) maps a hard backend failure to HTTP 409.
    """
    backend = run_git_update(BACKEND_REPO_DIR, BACKEND_BRANCH)
    if backend["status"] != "ok":
        return {"status": "error", "backend": backend}

    installs: list[Dict[str, Any]] = []
    for name in _lockfiles_changed(BACKEND_REPO_DIR, backend["previous_sha"], backend["new_sha"]):
        installs.append(_run_install(BACKEND_REPO_DIR, _LOCKFILE_INSTALLS[name]))

    frontend = run_git_update(FRONTEND_REPO_DIR, FRONTEND_BRANCH)
    frontend_changed = frontend.get("status") == "ok" and frontend.get("changed")
    if frontend_changed:
        for name in _lockfiles_changed(
            FRONTEND_REPO_DIR, frontend["previous_sha"], frontend["new_sha"]
        ):
            installs.append(_run_install(FRONTEND_REPO_DIR, _LOCKFILE_INSTALLS[name]))
        installs.append({"cmd": "npm run build", **_build_frontend_if_served()})

    changed = bool(backend.get("changed") or frontend_changed)
    result: Dict[str, Any] = {
        "status": "updated" if changed else "up_to_date",
        "backend": backend,
        "frontend": frontend,
        "installs": installs,
    }
    if changed and restart:
        schedule_self_restart()
        result["restarting"] = True
    return result


def schedule_self_restart(delay_s: float = 1.5) -> None:
    """Exit this process after ``delay_s`` on a daemon thread, so the HTTP
    response that triggered it flushes first. Whatever supervises the process
    (systemd ``Restart=always`` in prod) brings it back on the new code."""

    def _die() -> None:
        time.sleep(delay_s)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
