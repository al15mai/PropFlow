"""Tests for GET /admin/version and system_update.get_git_status (task D5)."""
from __future__ import annotations

import subprocess

import pytest

from system_update import get_git_status

_VERSION_KEYS = {
    "sha",
    "short_sha",
    "branch",
    "tag",
    "dirty",
    "commit_date",
    "commit_message",
    "available",
}


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def test_admin_version_endpoint_shape(client):
    r = client.get("/admin/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == _VERSION_KEYS
    assert isinstance(body["dirty"], bool)
    assert isinstance(body["available"], bool)
    assert body["short_sha"] == body["sha"][:7]


def test_get_git_status_on_non_repo_is_safe(tmp_path):
    """A directory that isn't a git repo yields empty fields, never an exception."""
    status = get_git_status(tmp_path)
    assert status["available"] is False
    assert status["sha"] == ""
    assert status["short_sha"] == ""
    assert status["dirty"] is False


@pytest.mark.skipif(not _git_available(), reason="git not on PATH")
def test_get_git_status_reports_this_repo():
    """Run against PropFlow/ itself (the default) — it's a real checkout."""
    status = get_git_status()
    assert status["available"] is True
    assert len(status["sha"]) == 40
    assert status["short_sha"] == status["sha"][:7]
    # branch is a name or "HEAD" when detached — never empty in a real checkout.
    assert status["branch"]
