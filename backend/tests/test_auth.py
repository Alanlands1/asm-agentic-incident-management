"""Sign-in: sessions, the cookie and the role checks."""

import pytest

from app.api.v1.endpoints.auth import COOKIE, current_user
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services import auth


@pytest.fixture
async def anon(client):
    """The client without the test admin: nobody is signed in until the test signs in."""
    app.dependency_overrides.pop(current_user)
    return client


async def _add_user(email: str, role: str, password: str = "correct horse", active: bool = True) -> None:
    async for db in app.dependency_overrides[get_db]():
        db.add(User(email=email, name="Ravi Kumar", role=role, password_hash=auth.hash_password(password), is_active=active))
        await db.commit()


def test_password_hash_is_salted_and_checks():
    stored = auth.hash_password("correct horse")
    assert "correct horse" not in stored and stored != auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("correct horse", "not a hash")


async def test_api_needs_a_session(anon):
    assert (await anon.get("/api/v1/tickets")).status_code == 401
    assert (await anon.get("/api/v1/auth/me")).status_code == 401
    assert (await anon.get("/api/v1/health")).status_code == 200  # the liveness probe stays open


async def test_sign_in_me_and_sign_out(anon):
    await _add_user("ravi@contoso.com", "engineer")
    r = await anon.post("/api/v1/auth/login", json={"email": " Ravi@Contoso.com ", "password": "correct horse"})
    assert r.status_code == 200
    assert r.json() == {"email": "ravi@contoso.com", "name": "Ravi Kumar", "role": "engineer"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert (await anon.get("/api/v1/auth/me")).json()["name"] == "Ravi Kumar"
    assert (await anon.get("/api/v1/tickets")).status_code == 200

    token = anon.cookies[COOKIE]
    assert (await anon.post("/api/v1/auth/logout")).status_code == 204
    anon.cookies.set(COOKIE, token)  # the old cookie no longer opens anything
    assert (await anon.get("/api/v1/auth/me")).status_code == 401


async def test_wrong_password_unknown_email_and_switched_off_user(anon):
    await _add_user("ravi@contoso.com", "engineer")
    await _add_user("gone@contoso.com", "engineer", active=False)
    for email, password in [("ravi@contoso.com", "wrong"), ("nobody@contoso.com", "correct horse"),
                            ("gone@contoso.com", "correct horse")]:
        r = await anon.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 401
        assert r.json()["detail"] == "Wrong email or password"
        assert "set-cookie" not in r.headers


async def test_expired_session_is_refused(anon, monkeypatch):
    await _add_user("ravi@contoso.com", "engineer")
    monkeypatch.setattr(auth.settings, "SESSION_HOURS", -1)
    await anon.post("/api/v1/auth/login", json={"email": "ravi@contoso.com", "password": "correct horse"})
    assert (await anon.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(("role", "reset", "assign", "admin", "people"), [
    ("engineer", 403, 403, 403, 403),
    ("lead", 403, 404, 403, 403),  # 404: allowed through to a ticket that does not exist
    ("admin", 200, 404, 503, 200),  # 503: allowed through to the admin key check (no key set here)
])
async def test_roles(anon, monkeypatch, role, reset, assign, admin, people):
    monkeypatch.setattr(auth.settings, "ADMIN_API_KEY", "")
    await _add_user("ravi@contoso.com", role)
    await anon.post("/api/v1/auth/login", json={"email": "ravi@contoso.com", "password": "correct horse"})
    assert (await anon.post("/api/v1/demo/reset?rerun=false")).status_code == reset
    r = await anon.post("/api/v1/tickets/NOPE-1/assign", json={"assignee": None, "by": "ravi@contoso.com"})
    assert r.status_code == assign
    assert (await anon.get("/api/v1/admin/settings")).status_code == admin
    r = await anon.get("/api/v1/auth/users")  # the admin's persona list
    assert r.status_code == people
    if people == 200:
        assert r.json() == [{"email": "ravi@contoso.com", "name": "Ravi Kumar", "role": "admin"}]


async def test_atlassian_sign_in(anon, monkeypatch):
    from pydantic import SecretStr

    from app.api.v1.endpoints.auth import STATE_COOKIE
    from app.services import atlassian_login

    monkeypatch.setattr(auth.settings, "ATLASSIAN_OAUTH_CLIENT_ID", "")  # whatever backend/.env says
    assert (await anon.get("/api/v1/auth/providers")).json() == {"atlassian": False}
    assert (await anon.get("/api/v1/auth/atlassian/start")).status_code == 503  # not set up

    monkeypatch.setattr(auth.settings, "ATLASSIAN_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setattr(auth.settings, "ATLASSIAN_OAUTH_CLIENT_SECRET", SecretStr("secret"))
    emails = {"good": "ravi@contoso.com", "stranger": "nobody@contoso.com"}

    async def email_of(code):
        if code not in emails:
            raise atlassian_login.AtlassianLoginError("bad code")
        return emails[code]

    monkeypatch.setattr(atlassian_login, "email_of", email_of)
    await _add_user("ravi@contoso.com", "lead")
    assert (await anon.get("/api/v1/auth/providers")).json() == {"atlassian": True}

    r = await anon.get("/api/v1/auth/atlassian/start")
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://auth.atlassian.com/authorize?")
    assert "client_id=client-1" in r.headers["location"]
    state = anon.cookies[STATE_COOKIE]
    assert f"state={state}" in r.headers["location"]

    async def back(code, state):
        return (await anon.get("/api/v1/auth/atlassian/callback", params={"code": code, "state": state})).headers["location"]

    # a callback that this browser did not start, a code Atlassian refuses, an account nobody added here
    assert await back("good", "someone-elses-state") == "/login?error=atlassian"
    for code, where in [("bad", "/login?error=atlassian"), ("stranger", "/login?error=no_access")]:
        anon.cookies.set(STATE_COOKIE, state)
        assert await back(code, state) == where
        assert (await anon.get("/api/v1/auth/me")).status_code == 401

    anon.cookies.set(STATE_COOKIE, state)
    assert await back("good", state) == "/"
    assert (await anon.get("/api/v1/auth/me")).json() == {"email": "ravi@contoso.com", "name": "Ravi Kumar", "role": "lead"}
