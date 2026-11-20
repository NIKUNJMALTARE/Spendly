"""Tests for the profile page: Step 4 design and Step 5 real expense data."""

import html
from html.parser import HTMLParser
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest

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
    # Unfiltered, the caption under the heading describes the whole history.
    assert re.search(r'class="profile-range">\s*All time\s*<', body)


def test_transactions_table(client):
    _login(client)
    body = _text(client.get("/profile"))
    headers = re.findall(r'<th scope="col"[^>]*>(.*?)</th>', body)
    assert headers[:4] == ["Date", "Description", "Category", "Amount"]
    assert len(headers) == 5
    assert 'class="visually-hidden">Actions<' in headers[4]
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


# ------------------------------------------------------------------ #
# Step 6: date filter                                                 #
# ------------------------------------------------------------------ #

FORMAT_ERROR = "Please enter valid dates (YYYY-MM-DD)."
ORDER_ERROR = "Start date must be on or before end date."
EN_DASH = "–"


def _filter_user(client):
    """Register a user with fixed March/April 2026 expenses and sign in."""
    email = "filter@example.com"
    _register_and_login(client, "Filter User", email)
    user_id = db_module.get_user_by_email(email)["id"]
    _add_expense(user_id, 100, "Food", "2026-03-01", "Mar first")
    _add_expense(user_id, 250, "Bills", "2026-03-15", "Mar mid")
    _add_expense(user_id, 200, "Food", "2026-03-31", "Mar last")
    _add_expense(user_id, 400, "Health", "2026-04-01", "Apr first")
    return user_id


def _get(client, **params):
    return client.get("/profile", query_string=params)


def _caption(body):
    match = re.search(r'class="profile-range">\s*(.*?)\s*</p>', body, re.S)
    assert match, "range caption not rendered"
    return match.group(1)


def _stat(body, label):
    match = re.search(
        r'stat-label">' + re.escape(label) + r'</span>\s*<span[^>]*class="stat-value"[^>]*>(.*?)</span>',
        body,
        re.S,
    )
    assert match, f"stat {label} not rendered"
    return match.group(1).strip()


class _TagCollector(HTMLParser):
    """Collect <form>, <input> and <a> tags as attr dicts, independent of attribute order."""

    def __init__(self):
        super().__init__()
        self.forms, self.inputs, self.links = [], [], []
        self._link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.forms.append(attrs)
        elif tag == "input":
            self.inputs.append(attrs)
        elif tag == "a":
            self._link = {"attrs": attrs, "text": ""}

    def handle_data(self, data):
        if self._link is not None:
            self._link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self._link["text"] = self._link["text"].strip()
            self.links.append(self._link)
            self._link = None


def _tags(body):
    collector = _TagCollector()
    collector.feed(body)
    return collector


def _classes(attrs):
    return (attrs.get("class") or "").split()


def _input_values(body):
    return {
        attrs["name"]: attrs.get("value") or ""
        for attrs in _tags(body).inputs
        if attrs.get("name") in ("start_date", "end_date")
    }


def _preset_links(body):
    return [link for link in _tags(body).links if "filter-preset" in _classes(link["attrs"])]


def _active_presets(body):
    return [
        link["text"]
        for link in _preset_links(body)
        if "is-active" in _classes(link["attrs"]) and link["attrs"].get("aria-current") == "true"
    ]


def _alert(body):
    match = re.search(r'<[^>]*role="alert"[^>]*>\s*(.*?)\s*<', body, re.S)
    return match.group(1) if match else None


def _assert_demo_all_time(body):
    assert _stat(body, "Total spent") == "₹7,350.00"
    assert _stat(body, "Transactions") == "8"
    assert _stat(body, "Top category") == "Shopping"
    assert _descriptions(_tbody(body)) == RECENT_FIVE
    assert _caption(body) == "All time"


class TestParseDateFilter:
    def test_empty_args(self):
        assert app_module._parse_date_filter({}) == (None, None, None)

    def test_blank_and_whitespace_values_are_none(self):
        args = {"start_date": "", "end_date": "   "}
        assert app_module._parse_date_filter(args) == (None, None, None)

    def test_valid_range(self):
        args = {"start_date": "2026-03-01", "end_date": "2026-03-31"}
        assert app_module._parse_date_filter(args) == ("2026-03-01", "2026-03-31", None)

    def test_only_start_and_only_end(self):
        assert app_module._parse_date_filter({"start_date": "2026-03-01"}) == (
            "2026-03-01", None, None)
        assert app_module._parse_date_filter({"end_date": "2026-03-31"}) == (
            None, "2026-03-31", None)

    def test_whitespace_is_stripped(self):
        args = {"start_date": " 2026-03-01 ", "end_date": "\t2026-03-02"}
        assert app_module._parse_date_filter(args) == ("2026-03-01", "2026-03-02", None)

    def test_value_is_normalised(self):
        assert app_module._parse_date_filter({"start_date": "2026-1-5"}) == (
            "2026-01-05", None, None)

    def test_equal_bounds_allowed(self):
        args = {"start_date": "2026-03-01", "end_date": "2026-03-01"}
        assert app_module._parse_date_filter(args) == ("2026-03-01", "2026-03-01", None)

    @pytest.mark.parametrize("bad", ["2026-02-30", "abc", "19/11/2026", "2026-13-01"])
    def test_invalid_value_gives_format_error_and_drops_both_bounds(self, bad):
        args = {"start_date": bad, "end_date": "2026-03-01"}
        assert app_module._parse_date_filter(args) == (None, None, FORMAT_ERROR)
        args = {"start_date": "2026-03-01", "end_date": bad}
        assert app_module._parse_date_filter(args) == (None, None, FORMAT_ERROR)

    def test_reversed_range_gives_order_error(self):
        args = {"start_date": "2026-03-31", "end_date": "2026-03-01"}
        assert app_module._parse_date_filter(args) == (None, None, ORDER_ERROR)

    def test_unknown_params_ignored(self):
        assert app_module._parse_date_filter({"foo": "bar"}) == (None, None, None)


class TestDatePresets:
    TODAY = date(2026, 3, 31)

    def _by_label(self, start, end, today=None):
        presets = app_module._date_presets(start, end, today=today or self.TODAY)
        return {p["label"]: p for p in presets}

    def test_labels_order_and_bounds(self):
        presets = app_module._date_presets(None, None, today=self.TODAY)
        assert [p["label"] for p in presets] == ["This month", "Last 30 days", "All time"]
        by = {p["label"]: p for p in presets}
        assert (by["This month"]["start_date"], by["This month"]["end_date"]) == (
            "2026-03-01", "2026-03-31")
        assert (by["Last 30 days"]["start_date"], by["Last 30 days"]["end_date"]) == (
            "2026-03-02", "2026-03-31")
        assert (by["All time"]["start_date"], by["All time"]["end_date"]) == (None, None)

    def test_all_time_active_without_filter(self):
        by = self._by_label(None, None)
        assert by["All time"]["active"] is True
        assert by["This month"]["active"] is False
        assert by["Last 30 days"]["active"] is False

    def test_this_month_active(self):
        by = self._by_label("2026-03-01", "2026-03-31")
        assert by["This month"]["active"] is True
        assert by["All time"]["active"] is False

    def test_last_30_days_active(self):
        by = self._by_label("2026-03-02", "2026-03-31")
        assert by["Last 30 days"]["active"] is True
        assert by["This month"]["active"] is False

    def test_active_requires_exact_match_on_both_bounds(self):
        by = self._by_label("2026-03-01", None)
        assert not any(p["active"] for p in by.values())
        by = self._by_label("2026-03-02", "2026-03-30")
        assert not any(p["active"] for p in by.values())

    def test_both_can_be_active_on_the_30th(self):
        by = self._by_label("2026-04-01", "2026-04-30", today=date(2026, 4, 30))
        assert by["This month"]["active"] is True
        assert by["Last 30 days"]["active"] is True


class TestShortDateFilter:
    def _filter(self):
        return app_module.app.jinja_env.filters["short_date"]

    def test_formats_date(self):
        assert self._filter()("2026-11-01") == "1 Nov 2026"
        assert self._filter()("2026-03-31") == "31 Mar 2026"

    def test_none_and_garbage_give_none(self):
        assert self._filter()(None) is None
        assert self._filter()("garbage") is None


class TestProfileDateFilterRoute:
    @pytest.mark.parametrize(
        "params", [{}, {"start_date": "", "end_date": ""}], ids=["no-params", "blank-submit"]
    )
    def test_no_filter_shows_all_time(self, client, params):
        _login(client)
        resp = _get(client, **params)
        assert resp.status_code == 200
        body = _text(resp)
        _assert_demo_all_time(body)
        assert _active_presets(body) == ["All time"]
        assert _input_values(body) == {"start_date": "", "end_date": ""}
        assert _alert(body) is None

    def test_filter_form_structure(self, client):
        _login(client)
        body = _text(_get(client))
        tags = _tags(body)
        form = next(f for f in tags.forms if "filter-form" in _classes(f))
        assert form.get("method") == "get"
        assert form.get("action") == "/profile"
        dates = {i["name"]: i.get("type") for i in tags.inputs if i.get("type") == "date"}
        assert dates == {"start_date": "date", "end_date": "date"}
        assert "Apply" in body

    def test_clear_link_points_to_bare_profile(self, client):
        _login(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        clear = [link for link in _tags(body).links if link["text"] == "Clear"]
        assert [link["attrs"].get("href") for link in clear] == ["/profile"]

    def test_inclusive_range_filters_stats_table_and_breakdown(self, client):
        _filter_user(client)
        resp = _get(client, start_date="2026-03-01", end_date="2026-03-31")
        assert resp.status_code == 200
        body = _text(resp)
        assert _stat(body, "Total spent") == "₹550.00"
        assert _stat(body, "Transactions") == "3"
        assert _stat(body, "Top category") == "Food"
        assert _descriptions(_tbody(body)) == ["Mar last", "Mar mid", "Mar first"]
        assert "Apr first" not in body
        assert 'aria-label="Food: ' in body
        assert 'aria-label="Bills: ' in body
        assert 'aria-label="Health: ' not in body
        percents = [int(p) for p in re.findall(r'aria-label="[^"]*: (\d+)%"', body)]
        assert sum(percents) == 100

    def test_single_day_range_includes_that_day(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-15", end_date="2026-03-15"))
        assert _stat(body, "Transactions") == "1"
        assert _descriptions(_tbody(body)) == ["Mar mid"]

    def test_caption_both_bounds(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        assert _caption(body) == f"1 Mar 2026 {EN_DASH} 31 Mar 2026"

    def test_start_only_is_from_caption_and_open_ended(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-15"))
        assert _caption(body) == "From 15 Mar 2026"
        assert _stat(body, "Transactions") == "3"
        assert _descriptions(_tbody(body)) == ["Apr first", "Mar last", "Mar mid"]

    def test_end_only_is_until_caption_and_open_ended(self, client):
        _filter_user(client)
        body = _text(_get(client, end_date="2026-03-15"))
        assert _caption(body) == "Until 15 Mar 2026"
        assert _stat(body, "Transactions") == "2"
        assert _descriptions(_tbody(body)) == ["Mar mid", "Mar first"]

    def test_inputs_prefilled_with_applied_bounds(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        assert _input_values(body) == {
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        }

    def test_inputs_prefilled_with_normalised_values(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date=" 2026-3-1 "))
        assert _input_values(body)["start_date"] == "2026-03-01"
        assert _input_values(body)["end_date"] == ""

    def test_unknown_params_ignored(self, client):
        _login(client)
        body = _text(_get(client, foo="bar"))
        _assert_demo_all_time(body)

    def test_each_preset_link_activates_itself(self, client):
        _login(client)
        links = _preset_links(_text(_get(client)))
        assert [link["text"] for link in links] == ["This month", "Last 30 days", "All time"]
        assert links[-1]["attrs"]["href"] == "/profile"
        for link in links:
            body = _text(client.get(link["attrs"]["href"]))
            assert link["text"] in _active_presets(body)
            assert _alert(body) is None

    def test_non_matching_range_marks_no_preset_active(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        assert _active_presets(body) == []

    @pytest.mark.parametrize("bad", ["2026-02-30", "abc", "19/11/2026"])
    def test_invalid_date_falls_back_to_all_time_with_alert(self, client, bad):
        _login(client)
        resp = _get(client, start_date=bad, end_date="2026-12-31")
        assert resp.status_code == 200
        body = _text(resp)
        assert _alert(body) == FORMAT_ERROR
        _assert_demo_all_time(body)

    def test_reversed_range_falls_back_with_alert(self, client):
        _login(client)
        resp = _get(client, start_date="2026-03-31", end_date="2026-03-01")
        assert resp.status_code == 200
        body = _text(resp)
        assert _alert(body) == ORDER_ERROR
        _assert_demo_all_time(body)
        assert _input_values(body) == {"start_date": "", "end_date": ""}

    def test_sql_injection_value_is_invalid_and_not_echoed(self, client):
        _login(client)
        evil = "2026-01-01' OR '1'='1"
        resp = _get(client, start_date=evil)
        assert resp.status_code == 200
        body = _text(resp)
        assert _alert(body) == FORMAT_ERROR
        _assert_demo_all_time(body)
        assert _input_values(body) == {"start_date": "", "end_date": ""}
        raw = resp.get_data(as_text=True)
        assert "OR '1'" not in raw and "OR &#39;1" not in raw

    def test_no_error_shown_for_valid_filter(self, client):
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        assert _alert(body) is None

    def test_empty_period_shows_zero_state(self, client):
        _login(client)
        body = _text(_get(client, start_date="2000-01-01", end_date="2000-01-31"))
        assert _stat(body, "Total spent") == "₹0.00"
        assert _stat(body, "Transactions") == "0"
        assert _stat(body, "Top category") == "—"
        assert "No transactions in this period." in body
        assert "No spending in this period." in body
        assert "No transactions yet." not in body
        assert "No spending yet." not in body
        assert "<tbody>" not in body

    def test_unfiltered_empty_user_keeps_step5_wording(self, client):
        _register_and_login(client, "Nobody", "nobody@example.com")
        body = _text(_get(client))
        assert "No transactions yet." in body
        assert "No spending yet." in body
        assert "in this period" not in body

    def test_filtered_view_never_shows_other_users_expenses(self, client):
        other = db_module.create_user("Other Person", "other@example.com", "password123")
        _add_expense(other, 9999, "Health", "2026-03-05", "Other secret")
        _filter_user(client)
        body = _text(_get(client, start_date="2026-03-01", end_date="2026-03-31"))
        assert "Other secret" not in body
        assert "9,999" not in body
        assert _stat(body, "Total spent") == "₹550.00"

    def test_signed_out_with_query_string_redirects_to_login(self, client):
        resp = _get(client, start_date="2026-03-01", end_date="2026-03-31")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"

    def test_signed_out_with_invalid_query_still_redirects(self, client):
        resp = _get(client, start_date="abc")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"


class TestDateFilterAssets:
    def test_css_has_filter_rules(self):
        css = CSS_PATH.read_text()
        for selector in (".filter-form", ".filter-preset.is-active", ".filter-error"):
            assert selector in css

    def test_claude_md_documents_date_filter(self):
        text = (PROJECT_ROOT / "CLAUDE.md").read_text()
        row = next(line for line in text.splitlines() if line.startswith("| `GET /profile`"))
        assert "start_date" in row and "end_date" in row
