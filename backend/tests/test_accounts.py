"""Account lifecycle: setup, login, lockout, password change, admin management, safety rules."""
import pytest
from fastapi.testclient import TestClient

from roadguard import auth
from roadguard.api import app
from roadguard.db import AuditLog, SessionLocal, User, init_db

GOOD = "Harbor-4821-Pine"
GOOD2 = "Quartz-7719-Sage"


@pytest.fixture()
def client():
    init_db()
    with SessionLocal() as s:
        s.query(User).delete()
        s.query(AuditLog).delete()
        s.commit()
    auth.throttle = auth.LoginThrottle()
    with TestClient(app) as c:
        yield c


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def setup_admin(c):
    r = c.post("/api/auth/setup", json={"username": "Chief", "full_name": "Chief Admin", "password": GOOD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_first_run_setup_only_once(client):
    assert client.get("/api/auth/status").json()["setup_needed"] is True
    tok = setup_admin(client)
    me = client.get("/api/auth/me", headers=hdr(tok)).json()
    assert me["username"] == "chief" and me["role"] == "admin" and me["full_name"] == "Chief Admin"
    assert client.get("/api/auth/status").json()["setup_needed"] is False
    assert client.post("/api/auth/setup", json={"username": "evil", "password": GOOD}).status_code == 409


def test_password_policy(client):
    for bad in ("short1A!", "alllowercaseletters", "chiefChief123"):
        assert client.post("/api/auth/setup", json={"username": "chief", "password": bad}).status_code == 422
    assert client.post("/api/auth/setup", json={"username": "x", "password": GOOD}).status_code == 422  # username


def test_login_lockout_after_repeated_failures(client):
    setup_admin(client)
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "chief", "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "chief", "password": GOOD})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_change_password_signs_out_other_sessions(client):
    tok = setup_admin(client)
    other = client.post("/api/auth/login", json={"username": "chief", "password": GOOD}).json()["token"]
    assert client.post("/api/auth/change-password", headers=hdr(tok),
                       json={"current_password": "nope", "new_password": GOOD2}).status_code == 400
    r = client.post("/api/auth/change-password", headers=hdr(tok), json={"current_password": GOOD, "new_password": GOOD2})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=hdr(other)).status_code == 401  # old session gone
    assert client.get("/api/auth/me", headers=hdr(r.json()["token"])).status_code == 200  # new one works
    assert client.post("/api/auth/login", json={"username": "chief", "password": GOOD2}).status_code == 200


def test_new_user_temp_password_must_be_changed(client):
    admin = setup_admin(client)
    r = client.post("/api/users", headers=hdr(admin), json={"username": "op1", "full_name": "Op One", "role": "operator"})
    assert r.status_code == 201
    temp = r.json()["temporary_password"]
    assert r.json()["user"]["must_change_password"] is True
    tok = client.post("/api/auth/login", json={"username": "op1", "password": temp}).json()["token"]
    assert client.get("/api/auth/me", headers=hdr(tok)).json()["must_change_password"] is True
    blocked = client.get("/api/stats/summary", headers=hdr(tok))
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    new = client.post("/api/auth/change-password", headers=hdr(tok),
                      json={"current_password": temp, "new_password": GOOD2}).json()["token"]
    assert client.get("/api/stats/summary", headers=hdr(new)).status_code == 200


def test_disable_role_change_and_reset_take_effect_immediately(client):
    admin = setup_admin(client)
    uid = client.post("/api/users", headers=hdr(admin),
                      json={"username": "ana", "role": "analyst", "password": GOOD2}).json()["user"]["id"]
    with SessionLocal() as s:  # skip the forced change for this test
        s.get(User, uid).must_change_password = False
        s.commit()
    tok = client.post("/api/auth/login", json={"username": "ana", "password": GOOD2}).json()["token"]
    assert client.get("/api/users", headers=hdr(tok)).status_code == 403  # analyst can't manage users
    client.patch(f"/api/users/{uid}", headers=hdr(admin), json={"role": "admin"})
    assert client.get("/api/users", headers=hdr(tok)).status_code == 200  # role from DB, not token
    client.patch(f"/api/users/{uid}", headers=hdr(admin), json={"active": False})
    assert client.get("/api/auth/me", headers=hdr(tok)).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ana", "password": GOOD2}).status_code == 403
    r = client.post(f"/api/users/{uid}/reset-password", headers=hdr(admin))
    assert r.status_code == 200 and r.json()["temporary_password"]


def test_admin_safety_rules(client):
    admin = setup_admin(client)
    me_id = client.get("/api/auth/me", headers=hdr(admin)).json()["id"]
    assert client.patch(f"/api/users/{me_id}", headers=hdr(admin), json={"active": False}).status_code == 409
    assert client.patch(f"/api/users/{me_id}", headers=hdr(admin), json={"role": "analyst"}).status_code == 409
    assert client.delete(f"/api/users/{me_id}", headers=hdr(admin)).status_code == 409
    uid = client.post("/api/users", headers=hdr(admin), json={"username": "tmp", "role": "operator"}).json()["user"]["id"]
    assert client.delete(f"/api/users/{uid}", headers=hdr(admin)).status_code == 204
    assert client.post("/api/users", headers=hdr(admin), json={"username": "chief", "role": "operator"}).status_code == 409


def test_logout_everywhere(client):
    tok = setup_admin(client)
    assert client.post("/api/auth/logout-all", headers=hdr(tok)).status_code == 200
    assert client.get("/api/auth/me", headers=hdr(tok)).status_code == 401


def test_dev_passwords_are_forced_to_change(client):
    with SessionLocal() as s:
        s.add(User(username="admin", role="admin", password_hash=auth.hash_password("roadguard-admin")))
        s.commit()
    auth.seed_users()
    with SessionLocal() as s:
        assert s.query(User).filter_by(username="admin").one().must_change_password is True


def test_analyze_rejects_non_videos(client):
    admin = setup_admin(client)
    r = client.post("/api/analyze", headers=hdr(admin), files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "Unsupported file type" in r.json()["detail"]
    r = client.post("/api/analyze", headers=hdr(admin), files={"file": ("fake.mp4", b"not really a video", "video/mp4")})
    assert r.status_code == 400 and "valid video" in r.json()["detail"]
    analyst_tok = client.post("/api/users", headers=hdr(admin), json={"username": "ana2", "role": "analyst", "password": GOOD2})
    assert analyst_tok.status_code == 201


def test_audit_trail(client):
    admin = setup_admin(client)
    client.post("/api/auth/login", json={"username": "chief", "password": "bad"})
    actions = [a["action"] for a in client.get("/api/audit", headers=hdr(admin)).json()]
    assert "setup_first_admin" in actions and "login_failed" in actions
