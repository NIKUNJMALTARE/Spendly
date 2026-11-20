"""Shared test helpers for Spendly's HTTP and DB tests.

Import what you need, e.g. ``from tests.helpers import DEMO, login, page_text``.
Feature-specific helpers (form defaults, post wrappers) stay in each test file.
"""

import html
import re
from datetime import date
from pathlib import Path

import database.db as db_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def today_iso():
    """Today's date as 'YYYY-MM-DD', the format date inputs submit."""
    return date.today().isoformat()


def login(client, **overrides):
    """Sign in as the demo user; keyword overrides replace email/password."""
    return client.post("/login", data={**DEMO, **overrides})


def register_and_login(client, name, email, password="password123"):
    """Create an account through /register, then sign in as it."""
    client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )
    return login(client, email=email, password=password)


def page_text(resp):
    """Response body with HTML entities decoded."""
    return html.unescape(resp.get_data(as_text=True))


def session_data(client):
    """A plain-dict copy of the client's current session."""
    with client.session_transaction() as sess:
        return dict(sess)


def alert_text(body):
    """Text of the first role="alert" element, or None."""
    match = re.search(r'role="alert"[^>]*>\s*(.*?)\s*<', body, re.S)
    return match.group(1) if match else None


def selected_options(body):
    """Values of every <option> marked selected."""
    return re.findall(r'<option value="([^"]*)"[^>]*\sselected', body)


def user_id_for(email):
    return db_module.get_user_by_email(email)["id"]


def expense_rows(user_id):
    """A user's expenses straight from the DB, oldest id first."""
    conn = db_module.get_db()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, user_id, amount, category, date, description "
                "FROM expenses WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def expense_count():
    """Total number of expense rows across all users."""
    conn = db_module.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()
