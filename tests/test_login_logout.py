"""Tests for Step 3 — login and logout."""

import html
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

import database.db as db_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}
INVALID = "Invalid email or password."
MISSING = "Please enter your email and password."


def _login(client, follow_redirects=False, **overrides):
    return client.post(
        "/login", data={**DEMO, **overrides}, follow_redirects=follow_redirects
    )


def _text(resp):
    # Jinja escapes apostrophes (&#39;), so compare against unescaped text.
    return html.unescape(resp.get_data(as_text=True))


def _session(client):
    with client.session_transaction() as sess:
        return dict(sess)


def _demo_user():
    return db_module.get_user_by_email(DEMO["email"])


# ------------------------------------------------------------------ #
# GET /login                                                          #
# ------------------------------------------------------------------ #

def test_get_login_renders_form(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    body = _text(resp)
    assert 'name="email"' in body
    assert 'name="password"' in body


def test_login_template_uses_url_for():
    source = (PROJECT_ROOT / "templates" / "login.html").read_text()
    assert "url_for('login')" in source
    assert 'action="/login"' not in source


# ------------------------------------------------------------------ #
# Successful login                                                    #
# ------------------------------------------------------------------ #

def test_demo_login_redirects_home(client):
    resp = _login(client)
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"


def test_demo_login_shows_welcome(client):
    resp = _login(client, follow_redirects=True)
    assert resp.request.path == "/"
    assert "Welcome back, Demo User!" in _text(resp)


def test_login_sets_session_without_secrets(client):
    _login(client)
    sess = _session(client)
    user = _demo_user()
    assert sess["user_id"] == user["id"]
    assert sess["user_name"] == "Demo User"
    assert set(sess) <= {"user_id", "user_name", "_flashes"}
    for value in sess.values():
        assert value != DEMO["password"]
        assert value != user["password_hash"]


def test_login_normalises_email(client):
    resp = _login(client, email="  DEMO@Spendly.com ")
    assert resp.status_code == 302
    assert "user_id" in _session(client)


def test_registered_user_can_login(client):
    client.post(
        "/register",
        data={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    resp = _login(client, email="test@example.com", password="password123")
    assert resp.status_code == 302
    assert _session(client)["user_name"] == "Test User"


def test_login_clears_previous_session(client):
    with client.session_transaction() as sess:
        sess["stale"] = "x"
    _login(client)
    assert "stale" not in _session(client)


# ------------------------------------------------------------------ #
# Failed login                                                        #
# ------------------------------------------------------------------ #

def _error_text(resp):
    match = re.search(r'<div class="auth-error">(.*?)</div>', _text(resp), re.S)
    return match.group(1).strip() if match else None


def test_wrong_password(client):
    resp = _login(client, password="wrong-password")
    assert resp.status_code == 200
    assert _error_text(resp) == INVALID
    assert "user_id" not in _session(client)


def test_unknown_email_same_message(client):
    wrong_pw = _login(client, password="wrong-password")
    unknown = _login(client, email="nobody@example.com")
    assert unknown.status_code == 200
    assert _error_text(unknown) == _error_text(wrong_pw) == INVALID
    assert "user_id" not in _session(client)


def test_password_not_stripped(client):
    resp = _login(client, password=" demo123")
    assert resp.status_code == 200
    assert _error_text(resp) == INVALID


@pytest.mark.parametrize(
    "email,password",
    [("", "demo123"), ("demo@spendly.com", ""), ("   ", "demo123"), ("", "")],
)
def test_missing_fields(client, email, password):
    resp = _login(client, email=email, password=password)
    assert resp.status_code == 200
    assert _error_text(resp) == MISSING
    assert "user_id" not in _session(client)


def test_failed_login_keeps_email_not_password(client):
    resp = _login(client, email=" Demo@Spendly.com ", password="wrong-pw-xyz")
    body = _text(resp)
    assert 'value="demo@spendly.com"' in body
    assert "wrong-pw-xyz" not in body


# ------------------------------------------------------------------ #
# Nav                                                                 #
# ------------------------------------------------------------------ #

def test_nav_signed_out(client):
    body = _text(client.get("/"))
    assert "Sign in" in body
    assert "Get started" in body
    assert "Sign out" not in body


def test_nav_signed_in(client):
    _login(client)
    body = _text(client.get("/"))
    assert "Demo User" in body
    assert "Sign out" in body
    assert 'href="/logout"' in body
    assert "Sign in" not in body
    assert "Get started" not in body


# ------------------------------------------------------------------ #
# Logout                                                              #
# ------------------------------------------------------------------ #

def test_logout_clears_session(client):
    _login(client)
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"
    assert "user_id" not in _session(client)
    assert "user_name" not in _session(client)


def test_logout_flash_and_nav(client):
    _login(client)
    resp = client.get("/logout", follow_redirects=True)
    assert resp.request.path == "/"
    body = _text(resp)
    assert "You've been signed out." in body
    assert "Sign in" in body
    assert "Sign out" not in body


def test_logout_when_signed_out(client):
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"
    assert client.get("/logout", follow_redirects=True).status_code == 200


def test_logout_stub_removed(client):
    resp = client.get("/logout", follow_redirects=True)
    assert "coming in Step 3" not in _text(resp)


# ------------------------------------------------------------------ #
# CSS, DB helper, docs                                                #
# ------------------------------------------------------------------ #

def test_signed_in_nav_css_has_no_hex():
    css = (PROJECT_ROOT / "static" / "css" / "style.css").read_text()
    match = re.search(r"/\* Signed-in nav.*?/\* End signed-in nav \*/", css, re.S)
    assert match, "signed-in nav CSS section not found"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", match.group(0))


def test_verify_user(app):
    user = db_module.verify_user(DEMO["email"], DEMO["password"])
    assert user is not None
    assert user["email"] == DEMO["email"]
    assert db_module.verify_user(DEMO["email"], "wrong") is None
    assert db_module.verify_user("nobody@example.com", "demo123") is None


def test_claude_md_route_table_updated():
    lines = (PROJECT_ROOT / "CLAUDE.md").read_text().splitlines()
    login_row = next(line for line in lines if line.startswith("| `GET/POST /login`"))
    logout_row = next(line for line in lines if line.startswith("| `GET /logout`"))
    assert "Implemented (Step 3)" in login_row
    assert "Implemented (Step 3)" in logout_row


# ------------------------------------------------------------------ #
# Signed-in users are kept away from the auth pages                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("path", ["/login", "/register"])
def test_signed_in_get_auth_page_redirects_home(client, path):
    _login(client)
    resp = client.get(path)
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"


def test_signed_in_post_login_keeps_session(client):
    _login(client)
    before = _session(client)["user_id"]
    resp = client.post("/login", data={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"
    assert _session(client)["user_id"] == before


def test_signed_in_post_register_creates_no_user(client):
    _login(client)
    resp = client.post(
        "/register",
        data={"name": "New", "email": "new@example.com", "password": "password123"},
    )
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/"
    assert db_module.get_user_by_email("new@example.com") is None


def test_auth_pages_still_reachable_after_logout(client):
    _login(client)
    client.get("/logout")
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
