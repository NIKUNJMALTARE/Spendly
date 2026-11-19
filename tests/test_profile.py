"""Tests for the profile page: Step 4 design and Step 5 real expense data."""

import html
import re
from datetime import date, datetime, timezone
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


RECENT_FIVE = [
    "Weekly groceries",
    "Gift wrapping",
    "Running shoes",
    "Movie tickets",
    "Pharmacy",
]


def _add_expense(user_id, amount, category, expense_date, description):
    conn = db_module.get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, category, expense_date, description),
            )
    finally:
        conn.close()


def _tbody(body):
    match = re.search(r"<tbody>(.*?)</tbody>", body, re.S)
    assert match, "transactions table not rendered"
    return match.group(1)


def _descriptions(tbody):
    # The description cell is the one right after the date cell.
    return [d.strip() for d in re.findall(r"</time></td>\s*<td>(.*?)</td>", tbody, re.S)]


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
    assert re.search(r'class="stat-value">\s*₹7,350\.00\s*<', body)
    assert re.search(r'class="stat-value">\s*8\s*<', body)
    assert re.search(r'class="stat-value">\s*Shopping\s*<', body)
    # Step 4 placeholder values are gone.
    assert "₹12,000.00" not in body
    assert not re.search(r'class="stat-value">\s*18\s*<', body)


def test_overview_heading(client):
    _login(client)
    body = _text(client.get("/profile"))
    assert re.search(r'id="overview-heading"[^>]*>\s*Overview\s*<', body)
    assert "This month" not in body


def test_transactions_table(client):
    _login(client)
    body = _text(client.get("/profile"))
    headers = re.findall(r'<th scope="col"[^>]*>(.*?)</th>', body)
    assert headers == ["Date", "Description", "Category", "Amount"]
    tbody = _tbody(body)
    assert tbody.count("<tr>") == 5
    assert _descriptions(tbody) == RECENT_FIVE
    for older in ("Electricity bill", "Monthly metro pass", "Lunch at cafe"):
        assert older not in tbody
    assert re.search(r'class="num nowrap">₹1,400\.00<', tbody)
    dates = re.findall(r'<time datetime="([^"]+)"', tbody)
    assert dates == sorted(dates, reverse=True)
    assert all(d <= date.today().isoformat() for d in dates)
    assert 'class="table-scroll"' in body


def test_empty_transactions_state(client):
    _register_and_login(client, "Fresh User", "fresh@example.com")
    body = _text(client.get("/profile"))
    assert re.search(r'class="stat-value">\s*₹0\.00\s*<', body)
    assert re.search(r'class="stat-value">\s*0\s*<', body)
    assert re.search(r'class="stat-value">\s*—\s*<', body)
    assert "No transactions yet." in body
    assert "No spending yet." in body
    assert "<table" not in body


def test_category_bars_match_percent(client):
    _login(client)
    raw = client.get("/profile").get_data(as_text=True)
    widths = re.findall(r'style="width: (\d+)%"', raw)
    assert widths == ["30", "25", "22", "8", "7", "6", "2"]


def test_placeholder_constants_removed():
    for name in (
        "PROFILE_STATS",
        "PROFILE_RECENT_TRANSACTIONS",
        "PROFILE_CATEGORY_BREAKDOWN",
    ):
        assert not hasattr(app_module, name)


def test_users_see_only_own_expenses(client):
    _register_and_login(client, "Bea Other", "bea@example.com")
    bea_id = _session(client)["user_id"]
    _add_expense(bea_id, 999.0, "Health", date.today().isoformat(), "Bea dentist visit")

    body = _text(client.get("/profile"))
    assert "Bea dentist visit" in body
    assert "Weekly groceries" not in body
    assert re.search(r'class="stat-value">\s*₹999\.00\s*<', body)

    client.get("/logout")
    _login(client)
    body = _text(client.get("/profile"))
    assert "Bea dentist visit" not in body
    assert re.search(r'class="stat-value">\s*₹7,350\.00\s*<', body)


def test_null_description_renders_dash(client):
    _login(client)
    _add_expense(_session(client)["user_id"], 10.0, "Other", date.today().isoformat(), None)
    tbody = _tbody(_text(client.get("/profile")))
    assert _descriptions(tbody)[0] == "—"
    assert "None" not in tbody


def test_html_description_escaped(client):
    _login(client)
    _add_expense(_session(client)["user_id"], 10.0, "Other", date.today().isoformat(), "<b>x</b>")
    raw = client.get("/profile").get_data(as_text=True)
    assert "&lt;b&gt;x&lt;/b&gt;" in raw
    assert "<b>x</b>" not in raw


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
    assert "Implemented (Step 4 design, Step 5 real data)" in row
    assert "get_user_by_id()" in text
    for helper in (
        "get_expense_stats()",
        "get_recent_expenses()",
        "get_category_breakdown()",
    ):
        assert helper in text


def test_login_lands_on_profile(client):
    resp = _login(client, follow_redirects=True)
    assert resp.request.path == "/profile"
    body = _text(resp)
    assert "Welcome back, Demo User!" in body
    assert _card_name(body) == "Demo User"
