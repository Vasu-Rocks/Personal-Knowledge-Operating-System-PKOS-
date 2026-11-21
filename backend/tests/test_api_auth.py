import uuid

import jwt
import pytest

from core import security

API = "/api/v1"


def test_health_reports_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] is True


def test_register_then_me(client, make_user):
    u = make_user("alice")
    r = client.get(f"{API}/me", headers=u.headers)
    assert r.status_code == 200
    assert r.json()["username"] == u.username and r.json()["email"] == u.email


def test_duplicate_email_and_username_rejected(client, make_user):
    u = make_user("bob")
    base = {"name": "X", "password": "correct-horse-battery"}
    r = client.post(f"{API}/register", json={**base, "email": u.email, "username": "other_" + uuid.uuid4().hex[:6]})
    assert r.status_code == 400
    r = client.post(f"{API}/register", json={**base, "email": "new_" + u.email, "username": u.username})
    assert r.status_code == 400


@pytest.mark.parametrize("email", ["no-at-sign", "a@b", "@"])
def test_invalid_email_rejected(client, email):
    r = client.post(f"{API}/register", json={
        "email": email, "username": "u_" + uuid.uuid4().hex[:6], "name": "N", "password": "correct-horse-battery"})
    assert r.status_code == 400


def test_login_with_email_and_username(client, make_user):
    u = make_user("carol")
    for ident in (u.email, u.username):
        r = client.post(f"{API}/login", data={"username": ident, "password": u.password})
        assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_login_wrong_password_and_unknown_user(client, make_user):
    u = make_user("dave")
    assert client.post(f"{API}/login", data={"username": u.email, "password": "nope"}).status_code == 401
    assert client.post(f"{API}/login", data={"username": "ghost_user", "password": "x"}).status_code == 401


def test_protected_routes_require_a_token(client):
    for method, path in [("get", "/me"), ("get", "/documents"), ("post", "/upload"),
                         ("post", "/query/stream"), ("get", "/graph/status")]:
        assert getattr(client, method)(f"{API}{path}").status_code == 401, path


def test_tampered_and_foreign_tokens_rejected(client, make_user):
    u = make_user("erin")
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {u.token}x"}).status_code == 401
    forged = jwt.encode({"sub": str(uuid.uuid4())}, "some-other-secret-0123456789abcdef!!", algorithm="HS256")
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_valid_token_for_unknown_user_rejected(client):
    token = security.create_access_token({"sub": str(uuid.uuid4())})
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# --- Registration rules (M2-7) ---

def test_short_password_rejected(client):
    r = client.post(f"{API}/register", json={
        "email": f"s_{uuid.uuid4().hex[:6]}@example.com", "username": "s_" + uuid.uuid4().hex[:6],
        "name": "S", "password": "abc"})
    assert r.status_code == 400


def test_email_lookup_is_case_insensitive(client, make_user):
    u = make_user("frank")
    r = client.post(f"{API}/login", data={"username": u.email.upper(), "password": u.password})
    assert r.status_code == 200


@pytest.mark.parametrize("username", ["ab", "has space", "bad/char", "x" * 33])
def test_invalid_username_rejected(client, username):
    r = client.post(f"{API}/register", json={
        "email": f"v_{uuid.uuid4().hex[:6]}@example.com", "username": username,
        "name": "V", "password": "correct-horse-battery"})
    assert r.status_code == 400


def test_email_is_stored_lowercase_and_duplicates_ignore_case(client, make_user):
    u = make_user("gina")
    r = client.post(f"{API}/register", json={
        "email": u.email.upper(), "username": "dup_" + uuid.uuid4().hex[:6],
        "name": "G", "password": "correct-horse-battery"})
    assert r.status_code == 400
    assert client.get(f"{API}/me", headers=u.headers).json()["email"] == u.email.lower()


def test_token_with_non_uuid_subject_is_401_not_500(client):
    token = security.create_access_token({"sub": "not-a-uuid"})
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
