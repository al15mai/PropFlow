"""D1e — owner-only project admin: rename / delete / remove-member / transfer.

All four routes are gated per-project ("are you *this* project's owner?"). A
member — or the owner of a *different* project — gets 403. Guards: can't remove
the owner, can't delete a populated project, can't delete your last project.
"""
from __future__ import annotations

import uuid


def _property_in(project_id):
    """A minimal valid Property stamped to `project_id`."""
    from models import Property

    return Property(
        id=uuid.uuid4().hex, address="1 Test St", unitNumber="1", rooms=2,
        rentAmount=1000.0, currency="RON", status="Occupied", type="Rental",
        image=None, projectId=project_id,
    )


def _accept_invite(client, project_id, email, role="member"):
    """Owner invites `email` into `project_id`; the invitee accepts. Returns
    (user_id, token)."""
    r = client.post("/auth/invite", json={"email": email, "projectId": project_id, "role": role})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    r = client.post("/auth/accept-invite", json={"token": token, "password": "memberpass1"})
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"], r.json()["token"]


# --- rename -----------------------------------------------------------------

def test_owner_renames_project(client):
    pid = client.owner_project_id
    r = client.put(f"/projects/{pid}", json={"name": "  Renamed Portfolio  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed Portfolio"  # trimmed

    r = client.get("/auth/me")
    assert any(p["id"] == pid and p["name"] == "Renamed Portfolio" for p in r.json()["projects"])


def test_rename_rejects_empty_name(client):
    r = client.put(f"/projects/{client.owner_project_id}", json={"name": "   "})
    assert r.status_code == 422


def test_member_cannot_rename(client):
    pid = client.owner_project_id
    _uid, member_token = _accept_invite(client, pid, "m1@test.local")
    client.set_token(member_token)
    r = client.put(f"/projects/{pid}", json={"name": "hijack"})
    assert r.status_code == 403


def test_outside_owner_cannot_rename(client):
    _u, other_pid, other_token = client.seed_user("outsider@test.local", project_name="Other")
    client.set_token(other_token)
    r = client.put(f"/projects/{client.owner_project_id}", json={"name": "nope"})
    assert r.status_code == 403


# --- remove member --------------------------------------------------------

def test_owner_removes_member(client):
    pid = client.owner_project_id
    member_id, _tok = _accept_invite(client, pid, "m2@test.local")

    r = client.delete(f"/projects/{pid}/members/{member_id}")
    assert r.status_code == 204

    roles = {m["id"]: m["role"] for m in client.get(f"/projects/{pid}/members").json()}
    assert member_id not in roles


def test_cannot_remove_owner(client):
    pid = client.owner_project_id
    r = client.delete(f"/projects/{pid}/members/{client.owner.id}")
    assert r.status_code == 409


def test_remove_unknown_member_is_idempotent(client):
    r = client.delete(f"/projects/{client.owner_project_id}/members/{uuid.uuid4().hex}")
    assert r.status_code == 204


def test_member_cannot_remove_anyone(client):
    pid = client.owner_project_id
    a_id, _ = _accept_invite(client, pid, "a@test.local")
    _b_id, b_token = _accept_invite(client, pid, "b@test.local")
    client.set_token(b_token)
    r = client.delete(f"/projects/{pid}/members/{a_id}")
    assert r.status_code == 403


# --- transfer ownership --------------------------------------------------

def test_owner_transfers_ownership(client):
    pid = client.owner_project_id
    member_id, member_token = _accept_invite(client, pid, "heir@test.local")

    r = client.post(f"/projects/{pid}/transfer", json={"userId": member_id})
    assert r.status_code == 200, r.text
    assert r.json()["ownerId"] == member_id

    roles = {m["id"]: m["role"] for m in client.get(f"/projects/{pid}/members").json()}
    assert roles[member_id] == "owner"
    assert roles[client.owner.id] == "member"

    # the old owner is now a plain member — can't rename
    r = client.put(f"/projects/{pid}", json={"name": "still mine?"})
    assert r.status_code == 403
    # the new owner can
    client.set_token(member_token)
    assert client.put(f"/projects/{pid}", json={"name": "mine now"}).status_code == 200


def test_transfer_to_non_member_rejected(client):
    r = client.post(
        f"/projects/{client.owner_project_id}/transfer", json={"userId": uuid.uuid4().hex}
    )
    assert r.status_code == 409


def test_transfer_requires_userid(client):
    r = client.post(f"/projects/{client.owner_project_id}/transfer", json={})
    assert r.status_code == 422


# --- delete --------------------------------------------------------------

def test_cannot_delete_last_project(client):
    r = client.delete(f"/projects/{client.owner_project_id}")
    assert r.status_code == 409
    assert "only project" in r.json()["detail"]


def test_cannot_delete_populated_project(client):
    """Owner has a 2nd, populated project — delete is refused until it's empty."""
    import api as api_mod

    pid = uuid.uuid4().hex
    api_mod.db.create_project(
        id=pid, name="Second", owner_id=client.owner.id, currency="RON",
        created_at="2026-08-29T00:00:00",
    )
    api_mod.db.create_property(_property_in(pid))

    r = client.delete(f"/projects/{pid}")
    assert r.status_code == 409
    assert "record" in r.json()["detail"]


def test_owner_deletes_empty_secondary_project(client):
    import api as api_mod

    pid = uuid.uuid4().hex
    api_mod.db.create_project(
        id=pid, name="Scratch", owner_id=client.owner.id, currency="RON",
        created_at="2026-08-29T00:00:00",
    )
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert api_mod.db.get_project(pid) is None
    # membership rows gone too
    assert api_mod.db.get_project_member_role(pid, client.owner.id) is None


def test_member_cannot_delete_project(client):
    pid = client.owner_project_id
    _uid, member_token = _accept_invite(client, pid, "m3@test.local")
    client.set_token(member_token)
    assert client.delete(f"/projects/{pid}").status_code == 403


# --- auth --------------------------------------------------------------

def test_all_routes_401_without_token(client):
    pid = client.owner_project_id
    client.set_token(None)
    assert client.put(f"/projects/{pid}", json={"name": "x"}).status_code == 401
    assert client.delete(f"/projects/{pid}").status_code == 401
    assert client.delete(f"/projects/{pid}/members/x").status_code == 401
    assert client.post(f"/projects/{pid}/transfer", json={"userId": "x"}).status_code == 401
