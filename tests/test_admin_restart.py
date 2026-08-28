"""POST /admin/restart and POST /admin/update — owner-gated (task D5b).

The engine itself (run_git_update, run_update, schedule_self_restart) is covered
by test_system_update.py against throwaway git repos. Here we only check the
route wiring: the owner gate, and that the api.py handler maps the engine's
result to the right HTTP shape. `system_update` is monkeypatched so no real git
runs and the process never actually exits.
"""
from __future__ import annotations

import pytest

import api as api_mod


@pytest.fixture(autouse=True)
def _no_real_restart(monkeypatch):
    """Never let a test exit the process; capture the call instead."""
    calls: list[float] = []
    monkeypatch.setattr(api_mod, "schedule_self_restart", lambda delay_s=1.5: calls.append(delay_s))
    return calls


# --- auth gate --------------------------------------------------------------

def test_restart_requires_auth(client):
    client.set_token(None)
    assert client.post("/admin/restart").status_code == 401
    assert client.post("/admin/update").status_code == 401


def test_restart_requires_owner(client):
    _user, _pid, token = client.seed_user("member@test.local", project_name=None)
    client.set_token(token)
    r = client.post("/admin/restart")
    assert r.status_code == 403
    assert r.json()["detail"] == "Owner only"
    assert client.post("/admin/update").status_code == 403


# --- /admin/restart -------------------------------------------------------

def test_restart_as_owner_schedules_exit(client, _no_real_restart):
    r = client.post("/admin/restart")
    assert r.status_code == 200
    assert r.json() == {"status": "restarting"}
    assert _no_real_restart == [1.5]  # schedule_self_restart called once


# --- /admin/update -------------------------------------------------------

def test_update_up_to_date_returns_200_no_restart(client, monkeypatch, _no_real_restart):
    monkeypatch.setattr(
        api_mod,
        "run_update",
        lambda: {"status": "up_to_date", "backend": {"status": "ok", "changed": False},
                 "frontend": {"status": "ok", "changed": False}, "installs": []},
    )
    r = client.post("/admin/update")
    assert r.status_code == 200
    assert r.json()["status"] == "up_to_date"
    assert _no_real_restart == []  # nothing changed -> no restart


def test_update_changed_returns_200_with_restarting(client, monkeypatch):
    monkeypatch.setattr(
        api_mod,
        "run_update",
        lambda: {"status": "updated", "backend": {"status": "ok", "changed": True},
                 "frontend": {"status": "ok", "changed": False},
                 "installs": [{"cmd": "uv sync --frozen --native-tls", "status": "ok"}],
                 "restarting": True},
    )
    r = client.post("/admin/update")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "updated"
    assert body["restarting"] is True


def test_update_dirty_backend_is_409_with_git_detail(client, monkeypatch, _no_real_restart):
    monkeypatch.setattr(
        api_mod,
        "run_update",
        lambda: {"status": "error", "backend": {"status": "dirty", "detail": " M api.py"}},
    )
    r = client.post("/admin/update")
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "dirty"
    assert _no_real_restart == []


def test_update_not_fast_forward_is_409(client, monkeypatch):
    monkeypatch.setattr(
        api_mod,
        "run_update",
        lambda: {"status": "error", "backend": {"status": "not_fast_forward", "detail": "diverged"}},
    )
    r = client.post("/admin/update")
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "not_fast_forward"
