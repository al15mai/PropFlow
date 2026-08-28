"""Auth backend — password hashing, JWT, and the /auth/* routes (task D1)."""
from __future__ import annotations

import uuid

import pytest

import auth


# --- primitives -----------------------------------------------------------

def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert auth.verify_password("correct horse battery staple", h)
    assert not auth.verify_password("wrong", h)


def test_password_hash_is_salted():
    assert auth.hash_password("same") != auth.hash_password("same")


def test_long_password_not_truncated():
    # bcrypt's raw 72-byte limit would make these collide without the prehash.
    a = "x" * 100 + "A"
    b = "x" * 100 + "B"
    assert not auth.verify_password(b, auth.hash_password(a))


def test_token_roundtrip():
    tok = auth.create_access_token("user-123", {"email": "a@b.co"})
    claims = auth.decode_token(tok)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "a@b.co"
    assert claims["exp"] > claims["iat"]


def test_garbage_token_rejected():
    with pytest.raises(Exception):
        auth.decode_token("not.a.jwt")


# --- db layer -----------------------------------------------------------------

def _mk_user(database, email="owner@example.com", pw="hunter2xx"):
    return database.create_user(
        id=uuid.uuid4().hex, email=email, name="Owner",
        password_hash=auth.hash_password(pw), avatar=None, created_at="2026-08-28T00:00:00",
    )


def test_get_user_by_email_is_case_insensitive(database):
    _mk_user(database, email="Owner@Example.com")
    assert database.get_user_by_email("owner@example.com") is not None


def test_project_members_populated(database):
    u = _mk_user(database)
    p = database.create_project(
        id="proj-1", name="Portfolio", owner_id=u.id, currency="RON",
        created_at="2026-08-28T00:00:00",
    )
    assert p.members == [u.id]
    assert database.is_project_member("proj-1", u.id)
    assert not database.is_project_member("proj-1", "nobody")


# --- routes -----------------------------------------------------------------

@pytest.fixture
def owner(client, db_path):
    """A seeded owner + their project, plus a valid bearer token."""
    import api as api_mod
    d = api_mod.db
    u = d.create_user(
        id=uuid.uuid4().hex, email="owner@example.com", name="Landlord",
        password_hash=auth.hash_password("ownerpass1"), avatar=None,
        created_at="2026-08-28T00:00:00",
    )
    proj = d.create_project(
        id="proj-main", name="Main", owner_id=u.id, currency="RON",
        created_at="2026-08-28T00:00:00",
    )
    tok = auth.create_access_token(u.id, {"email": u.email})
    return {"user": u, "project": proj, "token": tok, "headers": {"Authorization": f"Bearer {tok}"}}


def test_login_ok(client, owner):
    r = client.post("/auth/login", json={"email": "owner@example.com", "password": "ownerpass1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "owner@example.com"
    assert "passwordHash" not in body["user"]
    assert body["token"]
    assert [p["id"] for p in body["projects"]] == ["proj-main"]


def test_login_wrong_password(client, owner):
    r = client.post("/auth/login", json={"email": "owner@example.com", "password": "nope"})
    assert r.status_code == 401


def test_me_requires_token(client, owner):
    client.set_token(None)
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_returns_user_and_projects(client, owner):
    r = client.get("/auth/me", headers=owner["headers"])
    assert r.status_code == 200
    assert r.json()["user"]["id"] == owner["user"].id
    assert r.json()["token"]  # fresh token issued


def test_full_invite_flow(client, owner):
    # owner invites
    r = client.post(
        "/auth/invite",
        json={"email": "member@example.com", "name": "Mem", "projectId": "proj-main"},
        headers=owner["headers"],
    )
    assert r.status_code == 201
    raw_token = r.json()["token"]
    assert raw_token

    # invitee accepts
    r = client.post(
        "/auth/accept-invite",
        json={"token": raw_token, "password": "memberpass1"},
    )
    assert r.status_code == 200
    member = r.json()
    assert member["user"]["email"] == "member@example.com"
    assert [p["id"] for p in member["projects"]] == ["proj-main"]

    # invitee can now log in
    assert client.post(
        "/auth/login", json={"email": "member@example.com", "password": "memberpass1"}
    ).status_code == 200

    # token is single-use
    assert client.post(
        "/auth/accept-invite", json={"token": raw_token, "password": "again1234"}
    ).status_code == 404


def test_invite_rejects_existing_account(client, owner):
    r = client.post(
        "/auth/invite",
        json={"email": "owner@example.com", "projectId": "proj-main"},
        headers=owner["headers"],
    )
    assert r.status_code == 409


def test_non_member_cannot_invite(client, owner):
    import api as api_mod
    stranger = api_mod.db.create_user(
        id=uuid.uuid4().hex, email="stranger@example.com", name="S",
        password_hash=auth.hash_password("strangerx"), avatar=None,
        created_at="2026-08-28T00:00:00",
    )
    tok = auth.create_access_token(stranger.id, {})
    r = client.post(
        "/auth/invite",
        json={"email": "x@example.com", "projectId": "proj-main"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_accept_invite_unknown_token(client, owner):
    r = client.post("/auth/accept-invite", json={"token": "made-up", "password": "whatever1"})
    assert r.status_code == 404


def test_change_password(client, owner):
    r = client.post(
        "/auth/change-password",
        json={"email": "ignored", "password": "brandnew1"},
        headers=owner["headers"],
    )
    assert r.status_code == 204
    assert client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "ownerpass1"}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "brandnew1"}
    ).status_code == 200
