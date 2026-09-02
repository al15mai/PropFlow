"""Tenant authentication + password reset — the D1f routes.

A tenant signs in with email OR phone + a password the landlord generated;
first login forces a reset; a tenant token only unlocks that tenant's own data.
"""
from __future__ import annotations

import uuid

import pytest

import auth


def _make_tenant(client, *, name="Ana Pop", email="ana@example.com",
                 phone="+40 712 345 678", propertyId="prop-1"):
    """Create a tenant through the API and return (tenant_dict, initial_password)."""
    r = client.post("/tenants", json={
        "id": uuid.uuid4().hex[:9],
        "propertyId": propertyId,
        "name": name,
        "email": email,
        "phone": phone,
        "leaseStart": "2026-01-01",
        "leaseEnd": "2026-12-31",
        "deposit": 1000.0,
        "status": "Active",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initialPassword"]
    assert "passwordHash" not in body
    return body, body["initialPassword"]


# --- create returns a one-time password ------------------------------------

def test_create_tenant_returns_initial_password_and_forces_reset(client):
    body, pw = _make_tenant(client)
    assert body["hasLogin"] is True
    assert body["mustReset"] is True
    # the plaintext is not persisted — a re-fetch never carries it
    r = client.get("/tenants")
    got = next(t for t in r.json() if t["id"] == body["id"])
    assert "initialPassword" not in got
    assert got["hasLogin"] is True


# --- login by email and by phone ------------------------------------------

def test_tenant_login_by_email(client):
    body, pw = _make_tenant(client, email="bob@example.com")
    r = client.post("/auth/tenant-login", json={"identifier": "bob@example.com", "password": pw})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["tenant"]["id"] == body["id"]
    assert out["mustReset"] is True
    assert out["token"]


def test_tenant_login_by_phone_normalized(client):
    body, pw = _make_tenant(client, phone="+40 712 999 000")
    # a different textual form of the same number still matches
    r = client.post("/auth/tenant-login", json={"identifier": "0712999000", "password": pw})
    assert r.status_code == 200, r.text
    assert r.json()["tenant"]["id"] == body["id"]


def test_tenant_login_wrong_password(client):
    _make_tenant(client, email="carol@example.com")
    r = client.post("/auth/tenant-login", json={"identifier": "carol@example.com", "password": "nope"})
    assert r.status_code == 401


def test_tenant_login_unknown_identifier(client):
    r = client.post("/auth/tenant-login", json={"identifier": "ghost@example.com", "password": "x"})
    assert r.status_code == 401


# --- first-login password change -----------------------------------------

def test_tenant_change_password_clears_must_reset(client):
    body, pw = _make_tenant(client, email="dan@example.com")
    login = client.post("/auth/tenant-login", json={"identifier": "dan@example.com", "password": pw}).json()
    token = login["token"]

    r = client.post(
        "/auth/tenant/change-password",
        json={"currentPassword": pw, "newPassword": "my-new-passphrase"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204

    # old password no longer works; new one does, and mustReset is cleared
    assert client.post("/auth/tenant-login",
                       json={"identifier": "dan@example.com", "password": pw}).status_code == 401
    relogin = client.post("/auth/tenant-login",
                          json={"identifier": "dan@example.com", "password": "my-new-passphrase"})
    assert relogin.status_code == 200
    assert relogin.json()["mustReset"] is False


def test_tenant_change_password_wrong_current(client):
    body, pw = _make_tenant(client, email="eve@example.com")
    token = client.post("/auth/tenant-login",
                        json={"identifier": "eve@example.com", "password": pw}).json()["token"]
    r = client.post(
        "/auth/tenant/change-password",
        json={"currentPassword": "wrong", "newPassword": "another-long-one"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_tenant_change_password_too_short(client):
    body, pw = _make_tenant(client, email="fay@example.com")
    token = client.post("/auth/tenant-login",
                        json={"identifier": "fay@example.com", "password": pw}).json()["token"]
    r = client.post(
        "/auth/tenant/change-password",
        json={"currentPassword": pw, "newPassword": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


# --- landlord-triggered reset -------------------------------------------------

def test_landlord_resets_tenant_password(client):
    body, pw = _make_tenant(client, email="gil@example.com")
    r = client.post(f"/tenants/{body['id']}/reset-password")
    assert r.status_code == 200, r.text
    new_pw = r.json()["password"]
    assert new_pw and new_pw != pw

    # old password dead, new one works, reset is forced again
    assert client.post("/auth/tenant-login",
                       json={"identifier": "gil@example.com", "password": pw}).status_code == 401
    out = client.post("/auth/tenant-login",
                      json={"identifier": "gil@example.com", "password": new_pw})
    assert out.status_code == 200
    assert out.json()["mustReset"] is True


def test_reset_password_unknown_tenant(client):
    assert client.post("/tenants/nope/reset-password").status_code == 404


def test_reset_password_requires_landlord_token(client):
    body, pw = _make_tenant(client, email="hal@example.com")
    token = client.post("/auth/tenant-login",
                        json={"identifier": "hal@example.com", "password": pw}).json()["token"]
    # a tenant token is not a user token -> get_current_user 401s
    r = client.post(f"/tenants/{body['id']}/reset-password",
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# --- tenant token scope --------------------------------------------------------

def test_tenant_token_cannot_hit_landlord_routes(client):
    body, pw = _make_tenant(client, email="iris@example.com")
    token = client.post("/auth/tenant-login",
                        json={"identifier": "iris@example.com", "password": pw}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/tenants", headers=h).status_code == 401
    assert client.get("/transactions", headers=h).status_code == 401
    assert client.get("/properties", headers=h).status_code == 401
    assert client.get("/auth/me", headers=h).status_code == 401


def test_tenant_bootstrap_returns_only_own_slice(client):
    # two tenants, one transaction each
    a, a_pw = _make_tenant(client, name="A", email="a@x.co", phone="0700000001", propertyId="prop-A")
    b, b_pw = _make_tenant(client, name="B", email="b@x.co", phone="0700000002", propertyId="prop-B")

    client.post("/properties", json={
        "id": "prop-A", "address": "1 A St", "unitNumber": "1", "rooms": 2,
        "rentAmount": 500, "currency": "RON", "status": "Occupied", "type": "Rental",
    })
    for owner_tid, amt in ((a["id"], 111.0), (b["id"], 222.0)):
        client.post("/transactions", json={
            "id": uuid.uuid4().hex[:9], "date": "2026-02-01", "amount": amt,
            "type": "Income", "paymentMethod": "Transfer", "tenantId": owner_tid,
        })

    token = client.post("/auth/tenant-login",
                        json={"identifier": "a@x.co", "password": a_pw}).json()["token"]
    r = client.get("/tenant/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant"]["id"] == a["id"]
    assert data["property"]["id"] == "prop-A"
    assert [t["amount"] for t in data["transactions"]] == [111.0]  # not B's 222


def test_tenant_me_refreshes_token(client):
    body, pw = _make_tenant(client, email="jay@example.com")
    token = client.post("/auth/tenant-login",
                        json={"identifier": "jay@example.com", "password": pw}).json()["token"]
    r = client.get("/auth/tenant/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["tenant"]["id"] == body["id"]
    assert r.json()["token"]


# --- account-holder listing (feeds D9) --------------------------------------

def test_list_account_holder_tenants(client):
    a, _ = _make_tenant(client, name="Has Login", email="hl@x.co", phone="0700000010")
    # a tenant row with no password (create one directly in the db, no route does this)
    import api as api_mod
    api_mod.db.create_tenant(_bare_tenant("no-login", "No Login", "nl@x.co"))

    holders = api_mod.db.list_account_holder_tenants(None)
    ids = {h["id"] for h in holders}
    assert a["id"] in ids
    assert "no-login" not in ids


def test_account_holders_route_lists_only_login_tenants(client):
    """GET /projects/{id}/account-holders — the D9 endpoint."""
    a, _ = _make_tenant(client, name="Signs In", email="si@x.co", phone="0700000011")
    import api as api_mod
    api_mod.db.create_tenant(_bare_tenant("nl-2", "No Login 2", "nl2@x.co"))

    r = client.get(f"/projects/{client.owner_project_id}/account-holders")
    assert r.status_code == 200, r.text
    rows = r.json()
    ids = {h["id"] for h in rows}
    assert a["id"] in ids
    assert "nl-2" not in ids
    row = next(h for h in rows if h["id"] == a["id"])
    assert row["mustReset"] is True
    assert set(row) == {"id", "name", "email", "phone", "mustReset"}


def test_account_holders_route_denies_non_member(client):
    _make_tenant(client, email="member-check@x.co", phone="0700000012")
    _, other_pid, other_tok = client.seed_user("outsider@x.co", project_name="Other")
    import api as api_mod
    c2 = _client_with_token(api_mod, other_tok)
    # outsider asks for the owner's project -> 403
    assert c2.get(f"/projects/{client.owner_project_id}/account-holders").status_code == 403


def _client_with_token(api_mod, token):
    from _asgi import ASGIClient
    return ASGIClient(api_mod.app, headers={"Authorization": f"Bearer {token}"})


def _bare_tenant(tid, name, email):
    from models import Tenant
    return Tenant(
        id=tid, propertyId="p", name=name, email=email, phone="",
        leaseStart="2026-01-01", leaseEnd="2026-12-31", deposit=0.0, status="Active",
    )
