import re
import sqlite3
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

import app as app_module
import database.db as db_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID = {"name": "Test User", "email": "test@example.com", "password": "password123"}
DUPLICATE_MSG = "An account with that email already exists."


def _post(client, follow_redirects=False, **overrides):
    data = {**VALID, **overrides}
    return client.post("/register", data=data, follow_redirects=follow_redirects)


def _count_users(email=None):
    conn = db_module.get_db()
    try:
        if email is None:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?", (email,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_get_register_renders_form(client):
    resp = client.get("/register")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Full name" in html
    for field in ("name", "email", "password"):
        assert f'name="{field}"' in html


def test_register_success_redirects_to_login(client):
    resp = _post(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_register_success_shows_flash(client):
    resp = _post(client, follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == "/login"
    assert "Account created — please sign in." in resp.get_data(as_text=True)


def test_register_stores_hashed_password(client):
    _post(client)
    row = db_module.get_user_by_email("test@example.com")
    assert row is not None
    assert row["password_hash"] != "password123"
    assert check_password_hash(row["password_hash"], "password123")


def test_register_normalises_email_and_name(client):
    _post(client, email="  Test@Example.com ", name="  Test User ")
    row = db_module.get_user_by_email("test@example.com")
    assert row is not None
    assert row["name"] == "Test User"


@pytest.mark.parametrize("email", ["demo@spendly.com", "DEMO@Spendly.com"])
def test_register_duplicate_email(client, email):
    before = _count_users()
    resp = _post(client, email=email)
    assert resp.status_code == 200
    assert DUPLICATE_MSG in resp.get_data(as_text=True)
    assert _count_users() == before
    assert _count_users("demo@spendly.com") == 1


def test_register_integrity_error_race(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_user_by_email", lambda email: None)
    before = _count_users()
    resp = _post(client, email="demo@spendly.com")
    assert resp.status_code == 200
    assert DUPLICATE_MSG in resp.get_data(as_text=True)
    assert _count_users() == before


@pytest.mark.parametrize("name", ["", "   "])
def test_register_empty_name(client, name):
    before = _count_users()
    resp = _post(client, name=name)
    assert resp.status_code == 200
    assert "Please enter your name." in resp.get_data(as_text=True)
    assert _count_users() == before


@pytest.mark.parametrize("email", ["not-an-email", "@x.com", "a@b", "a@@b.com", ""])
def test_register_malformed_email(client, email):
    before = _count_users()
    resp = _post(client, email=email)
    assert resp.status_code == 200
    assert "Please enter a valid email address." in resp.get_data(as_text=True)
    assert _count_users() == before


@pytest.mark.parametrize("password", ["short", ""])
def test_register_short_password(client, password):
    before = _count_users()
    resp = _post(client, password=password)
    assert resp.status_code == 200
    assert "Password must be at least 8 characters." in resp.get_data(as_text=True)
    assert _count_users() == before


def test_register_password_exactly_8_ok(client):
    resp = _post(client, password="12345678")
    assert resp.status_code == 302
    assert _count_users("test@example.com") == 1


def test_failed_submit_keeps_name_and_email(client):
    resp = _post(client, password="tiny-pw")
    html = resp.get_data(as_text=True)
    assert 'value="Test User"' in html
    assert 'value="test@example.com"' in html
    assert "tiny-pw" not in html


def test_error_rerender_is_200_not_redirect(client):
    resp = _post(client, password="short")
    assert resp.status_code == 200
    assert "Location" not in resp.headers


def test_register_template_uses_url_for():
    source = (PROJECT_ROOT / "templates" / "register.html").read_text()
    assert "url_for('register')" in source
    assert 'action="/register"' not in source


def test_style_css_flash_rules_have_no_hex():
    css = (PROJECT_ROOT / "static" / "css" / "style.css").read_text()
    match = re.search(r"/\* Flash messages.*?/\* End flash messages \*/", css, re.S)
    assert match, "Flash messages section not found"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", match.group(0))


def test_db_helpers(app):
    assert db_module.get_user_by_email("nobody@example.com") is None
    user_id = db_module.create_user("Helper", "helper@example.com", "password123")
    assert isinstance(user_id, int)
    with pytest.raises(sqlite3.IntegrityError):
        db_module.create_user("Helper 2", "helper@example.com", "password123")
