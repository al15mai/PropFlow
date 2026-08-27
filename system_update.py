"""Git version introspection for ``GET /admin/version`` (task D5, part 1).

Only the read-only *version display* half of D5 lives here. The self-update /
restart engine (``run_git_update``, ``schedule_self_restart``) is deferred until
both repos sit on clean, fast-forwardable branch tips (tasks C3 / D6) and will be
added here later, mirroring ``Automated_yt_web/system_update.py`` in SongFlow.

Everything degrades gracefully: if ``git`` is missing, the directory isn't a
repo, or a command fails, each field falls back to an empty-ish value and
``available`` is ``False`` — the endpoint never raises.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

# The backend repo (PropFlow/) is this file's own directory.
BACKEND_REPO_DIR = Path(__file__).resolve().parent


def _git(repo_dir: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def get_git_status(repo_dir: Path | str = BACKEND_REPO_DIR) -> Dict[str, Any]:
    """Commit / branch / tag / dirty state of ``repo_dir`` for the version card."""
    repo_dir = Path(repo_dir)

    sha = _git(repo_dir, "rev-parse", "HEAD")
    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")  # "HEAD" when detached
    tags = _git(repo_dir, "tag", "--points-at", "HEAD")
    log_line = _git(repo_dir, "log", "-1", "--format=%cI%x09%s")
    commit_date, _, commit_message = log_line.partition("\t")

    return {
        "sha": sha,
        "short_sha": sha[:7],
        "branch": branch,
        "tag": tags.splitlines()[0] if tags else "",
        "dirty": bool(_git(repo_dir, "status", "--porcelain")),
        "commit_date": commit_date,
        "commit_message": commit_message,
        "available": bool(sha),
    }
