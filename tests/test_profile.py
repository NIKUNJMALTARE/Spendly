"""Tests for Step 4 — profile page design."""

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import app as app_module
import database.db as db_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "profile.html"
CSS_PATH = PROJECT_ROOT / "static" / "css" / "profile.css"
DEMO = {"email": "demo@spendly.com", "password": "demo123"}
SIGN_IN_MESSAGE = "Please sign in to view your profile."
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _login(client, follow_redirects=False, **overrides):
    return client.post(
        "/login", data={**DEMO, **overrides}, follow_redirects=follow_redirects
    )


def _register_and_login(client, name, email, password="password123"):
    client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )
    return _login(client, email=email, password=password)


def _text(resp):
    # Jinja escapes apostrophes (&#39;), so compare against unescaped text.
    return html.unescape(resp.get_data(as_text=True))


def _session(client):
    with client.session_transaction() as sess:
        return dict(sess)


def _card_name(body):
    match = re.search(r'class="profile-name">(.*?)</h1>', body)
    assert match, "profile name not rendered"
    return match.group(1)


def _avatar(body):
    match = re.search(r'class="profile-avatar"[^>]*>\s*(.*?)\s*<', body)
    assert match, "avatar not rendered"
    return match.group(1)


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_signed_out_redirects_to_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/login"


def test_signed_out_flash_shown(client):
    resp = client.get("/profile", follow_redirects=True)
    assert resp.request.path == "/login"
    assert SIGN_IN_MESSAGE in _text(resp)


def test_signed_out_sets_no_session(client):
    client.get("/profile")
    assert "user_id" not in _session(client)


def test_stale_session_redirects_and_clears(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999
        sess["user_name"] = "Ghost"
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/login"
    sess = _session(client)
    assert "user_id" not in sess and "user_name" not in sess

    resp = client.get("/login")
    assert resp.status_code == 200
    assert SIGN_IN_MESSAGE in _text(resp)


def test_deleted_user_session_redirects(client):
    _register_and_login(client, "Temp User", "temp@example.com")
    user_id = _session(client)["user_id"]
    conn = db_module.get_db()
    try:
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    finally:
        conn.close()

    resp = client.get("/profile")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/login"
    assert "user_id" not in _session(client)


# ------------------------------------------------------------------ #
# User card                                                           #
# ------------------------------------------------------------------ #

def test_demo_profile_renders(client):
    _login(client)
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = _text(resp)
    assert _card_name(body) == "Demo User"
    assert re.search(r'class="profile-email">demo@spendly\.com<', body)
    # The seed runs inside the test, so created_at is "now" (UTC).
    assert "Member since " + datetime.now(timezone.utc).strftime("%B %Y") in body


def test_avatar_initials(client):
    _login(client)
    assert _avatar(_text(client.get("/profile"))) == "DU"


def test_initials_single_word_name(client):
    _register_and_login(client, "Cher", "cher@example.com")
    assert _avatar(_text(client.get("/profile"))) == "C"


def test_initials_multi_word_name(client):
    _register_and_login(client, "Mary Jane Watson", "mjw@example.com")
    assert _avatar(_text(client.get("/profile"))) == "MW"


def test_new_user_sees_own_profile(client):
    _register_and_login(client, "Asha Rao", "asha@example.com")
    body = _text(client.get("/profile"))
    assert _card_name(body) == "Asha Rao"
    assert re.search(r'class="profile-email">asha@example\.com<', body)
    assert "demo@spendly.com" not in body
    assert "Demo User" not in body


def test_html_name_escaped(client):
    _register_and_login(client, "<b>x</b>", "xss@example.com")
    raw = client.get("/profile").get_data(as_text=True)
    assert _card_name(raw) == "&lt;b&gt;x&lt;/b&gt;"
    assert "<b>x</b>" not in raw


def test_month_year_filter():
    fmt = app_module._format_month_year
    assert fmt("2026-11-18 10:00:00") == "November 2026"
    assert fmt(None) is None
    assert fmt("") is None
    assert fmt("garbage") is None


def test_inr_filter():
    assert app_module._format_inr(12000) == "₹12,000.00"
    assert app_module._format_inr(8.5) == "₹8.50"


# ------------------------------------------------------------------ #
# Stats, transactions, category breakdown                             #
# ------------------------------------------------------------------ #

def test_stat_cards(client):
    _login(client)
    body = _text(client.get("/profile"))
    for label in ("Total spent", "Transactions", "Top category"):
        assert label in body
    assert re.search(r'class="stat-value">\s*₹12,000\.00\s*<', body)
    assert re.search(r'class="stat-value">\s*18\s*<', body)
    assert re.search(r'class="stat-value">\s*Bills\s*<', body)


def test_transactions_table(client):
    _login(client)
    body = _text(client.get("/profile"))
    headers = re.findall(r'<th scope="col"[^>]*>(.*?)</th>', body)
    assert headers == ["Date", "Description", "Category", "Amount"]
    tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.S).group(1)
    assert tbody.count("<tr>") == 5
    for txn in app_module.PROFILE_RECENT_TRANSACTIONS:
        assert txn["description"] in tbody
    assert re.search(r'class="num nowrap">₹1,240\.00<', tbody)
    assert 'class="table-scroll"' in body


def test_empty_transactions_state(client, monkeypatch):
    monkeypatch.setattr(app_module, "PROFILE_RECENT_TRANSACTIONS", [])
    _login(client)
    body = _text(client.get("/profile"))
    assert "No transactions yet." in body
    assert "<table" not in body


def test_category_bars_match_percent(client):
    _login(client)
    raw = client.get("/profile").get_data(as_text=True)
    widths = re.findall(r'style="width: (\d+)%"', raw)
    expected = [str(c["percent"]) for c in app_module.PROFILE_CATEGORY_BREAKDOWN]
    assert widths == expected


def test_placeholder_data_consistent():
    breakdown = app_module.PROFILE_CATEGORY_BREAKDOWN
    stats = app_module.PROFILE_STATS
    assert sum(c["percent"] for c in breakdown) == 100
    assert all(isinstance(c["percent"], int) for c in breakdown)
    assert all(c["name"] in db_module.CATEGORIES for c in breakdown)
    assert sum(c["amount"] for c in breakdown) == stats["total_spent"]
    assert stats["top_category"] == max(breakdown, key=lambda c: c["amount"])["name"]

    txns = app_module.PROFILE_RECENT_TRANSACTIONS
    assert len(txns) == 5
    assert stats["transaction_count"] >= len(txns)
    for txn in txns:
        assert set(txn) == {"date", "description", "category", "amount"}
        assert txn["category"] in db_module.CATEGORIES


# ------------------------------------------------------------------ #
# Stub, nav, template and CSS rules                                   #
# ------------------------------------------------------------------ #

def test_profile_stub_removed(client):
    _login(client)
    assert "coming in Step 4" not in _text(client.get("/profile"))


def test_nav_name_links_to_profile_signed_in(client):
    _login(client)
    body = _text(client.get("/"))
    assert re.search(r'<a href="/profile" class="nav-user">Demo User</a>', body)


def test_nav_signed_out_unchanged(client):
    body = _text(client.get("/"))
    assert 'href="/profile"' not in body
    assert "nav-user" not in body
    assert "Sign in" in body
    assert "Get started" in body


def test_template_extends_base_and_loads_css(client):
    source = TEMPLATE_PATH.read_text()
    assert '{% extends "base.html" %}' in source
    assert "url_for('static', filename='css/profile.css')" in source
    _login(client)
    assert "/static/css/profile.css" in _text(client.get("/profile"))


def test_template_no_style_tags_or_safe():
    source = TEMPLATE_PATH.read_text()
    assert "<style" not in source
    assert re.findall(r'style="[^"]*"', source) == [
        'style="width: {{ item.percent }}%"'
    ]
    assert "|safe" not in source.replace(" ", "")


def test_profile_css_has_no_hex():
    assert not HEX_RE.search(CSS_PATH.read_text())


def test_profile_css_responsive_rules():
    css = CSS_PATH.read_text()
    assert "@media (max-width: 768px)" in css
    responsive = css.split("@media (max-width: 768px)", 1)[1]
    assert ".profile-stats" in responsive
    assert "grid-template-columns: 1fr" in responsive
    assert "overflow-x: auto" in css


def test_get_user_by_id(app):
    demo = db_module.get_user_by_email(DEMO["email"])
    user = db_module.get_user_by_id(demo["id"])
    assert user["name"] == "Demo User"
    assert user["email"] == DEMO["email"]
    assert "password_hash" not in user.keys()
    assert db_module.get_user_by_id(99999) is None


def test_claude_md_profile_row():
    text = (PROJECT_ROOT / "CLAUDE.md").read_text()
    row = next(line for line in text.splitlines() if line.startswith("| `GET /profile`"))
    assert "Implemented (Step 4)" in row
    assert "get_user_by_id()" in text


def test_login_lands_on_profile(client):
    resp = _login(client, follow_redirects=True)
    assert resp.request.path == "/profile"
    body = _text(resp)
    assert "Welcome back, Demo User!" in body
    assert _card_name(body) == "Demo User"
