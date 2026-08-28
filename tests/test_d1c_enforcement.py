"""D1c: every data route needs a token, and a caller sees only their project(s)."""
from __future__ import annotations

import pytest

DATA_GETS = ["/properties", "/tenants", "/transactions", "/maintenance", "/alerts",
             "/documents", "/invoice-templates"]


@pytest.mark.parametrize("path", DATA_GETS)
def test_data_route_requires_token(client, path):
    client.set_token(None)
    assert client.get(path).status_code == 401


def test_health_and_version_stay_open(client):
    client.set_token(None)
    assert client.get("/health").status_code == 200
    assert client.get("/admin/version").status_code == 200


def _mk_property(pid):
    return {
        "id": "p-" + pid, "address": "x", "unitNumber": "1", "rooms": 2,
        "rentAmount": 1000.0, "currency": "RON", "status": "Vacant", "type": "Rental",
        "projectId": pid,
    }


def test_caller_sees_only_their_project(client):
    # owner (proj-test) creates a property; a second account in its own project
    # must not see it.
    r = client.post("/properties", json=_mk_property(client.owner_project_id))
    assert r.status_code == 200

    _u, other_pid, other_tok = client.seed_user("other@test.local", project_name="Other")
    client.set_token(other_tok)

    got = client.get("/properties").json()
    assert all(p["projectId"] != client.owner_project_id for p in got)

    # ...and cannot read it by asking for the owner's project id explicitly
    assert client.get(f"/properties?projectId={client.owner_project_id}").status_code == 403


def test_legacy_null_project_rows_visible_to_everyone(client):
    # Pre-D1 rows have projectId = NULL — "shared / legacy", visible in every
    # project (D4b lenient filter). The API now stamps a project on create, so
    # such a row can only exist from before: insert one straight into the db.
    import api as api_mod
    from models import Property
    api_mod.db.create_property(Property(**{**_mk_property("null"), "projectId": None}))

    _u, _pid, other_tok = client.seed_user("x@test.local", project_name="X")
    client.set_token(other_tok)
    got = client.get("/properties").json()
    assert any(p["id"] == "p-null" for p in got)


def test_cross_project_write_rejected(client):
    r = client.post("/properties", json=_mk_property(client.owner_project_id))
    prop = r.json()

    _u, _pid, other_tok = client.seed_user("w@test.local", project_name="W")
    client.set_token(other_tok)

    prop["address"] = "hacked"
    assert client.put(f"/properties/{prop['id']}", json=prop).status_code == 403
    assert client.delete(f"/properties/{prop['id']}").status_code == 403


def test_create_stamps_the_callers_project(client):
    body = _mk_property("stamp")
    body.pop("projectId")
    r = client.post("/properties", json=body)
    assert r.status_code == 200
    assert r.json()["projectId"] == client.owner_project_id


def test_user_with_no_project_is_403(client):
    _u, _pid, tok = client.seed_user("orphan@test.local", project_name=None)
    client.set_token(tok)
    assert client.get("/properties").status_code == 403


def test_settings_is_owner_only(client):
    _u, _pid, member_tok = client.seed_user("member@test.local", project_name=None)
    # a plain member of the owner's project — not an owner anywhere
    import api as api_mod
    api_mod.db.add_project_member(client.owner_project_id, _u.id, "member")

    body = {"displayName": "x", "email": "x@x.co", "phone": "", "companyName": "",
            "currency": "RON", "language": "ro"}

    client.set_token(member_tok)
    assert client.post("/settings", json=body).status_code == 403

    client.set_token(client.owner_token)
    assert client.post("/settings", json=body).status_code == 200
