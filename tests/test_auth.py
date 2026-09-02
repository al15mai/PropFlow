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


# --- tenant auth primitives (task D1f) --------------------------------------

def test_generate_password_shape():
    pw = auth.generate_password()
    assert len(pw) == 10
    # ambiguity-free alphabet: no 0/O/1/l/I
    assert not (set(pw) & set("0O1lI"))
    assert auth.generate_password() != auth.generate_password()


def test_tenant_token_roundtrip_and_scope():
    tok = auth.create_tenant_token("t-42", {"name": "Ana"})
    claims = auth.decode_token(tok)
    assert claims["sub"] == "tenant:t-42"
    assert claims["scope"] == "tenant"
    assert auth.tenant_id_from_claims(claims) == "t-42"


def test_tenant_id_from_claims_rejects_landlord_token():
    landlord = auth.decode_token(auth.create_access_token("u-1", {"email": "a@b.co"}))
    assert auth.tenant_id_from_claims(landlord) is None
    # a token that claims scope=tenant but has no prefix is also rejected
    assert auth.tenant_id_from_claims({"sub": "u-1", "scope": "tenant"}) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+40 712 345 678", "712345678"),
        ("0712345678", "712345678"),
        ("0040712345678", "712345678"),
        ("0712-345-678", "712345678"),
        ("(0712) 345 678", "712345678"),
        ("712345678", "712345678"),
        ("", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert auth.normalize_phone(raw) == expected


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


def test_project_members_endpoint(client, owner):
    # after an invite is accepted, both show up on the members list
    r = client.post(
        "/auth/invite",
        json={"email": "mem2@example.com", "name": "Mem Two", "projectId": "proj-main"},
        headers=owner["headers"],
    )
    tok = r.json()["token"]
    client.post("/auth/accept-invite", json={"token": tok, "password": "mem2pass12"})

    r = client.get("/projects/proj-main/members", headers=owner["headers"])
    assert r.status_code == 200
    members = r.json()
    by_email = {m["email"]: m for m in members}
    assert by_email["owner@example.com"]["role"] == "owner"
    assert by_email["mem2@example.com"]["role"] == "member"


def test_project_members_requires_membership(client, owner):
    import api as api_mod
    outsider = api_mod.db.create_user(
        id=uuid.uuid4().hex, email="out@example.com", name="Out",
        password_hash=auth.hash_password("outpass12"), avatar=None,
        created_at="2026-08-28T00:00:00",
    )
    tok = auth.create_access_token(outsider.id, {})
    assert client.get(
        "/projects/proj-main/members", headers={"Authorization": f"Bearer {tok}"}
    ).status_code == 403
    client.set_token(None)
    assert client.get("/projects/proj-main/members").status_code == 401


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
