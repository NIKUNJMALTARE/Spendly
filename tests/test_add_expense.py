"""Tests for Step 7: adding an expense at /expenses/add."""

import re
import sqlite3
from datetime import date, timedelta

import pytest

import app as app_module
import database.db as db_module
from tests.helpers import (
    PROJECT_ROOT,
    DEMO,
    HEX_RE,
    today_iso,
    login,
    register_and_login,
    page_text,
    session_data,
    alert_text,
    selected_options,
    user_id_for,
    expense_rows,
    expense_count,
)

TEMPLATE_PATH = PROJECT_ROOT / "templates" / "add_expense.html"
CSS_PATH = PROJECT_ROOT / "static" / "css" / "add_expense.css"
PROFILE_CSS_PATH = PROJECT_ROOT / "static" / "css" / "profile.css"
SIGN_IN_MESSAGE = "Please sign in to add an expense."

AMOUNT_REQUIRED = "Please enter an amount greater than zero."
AMOUNT_MAX = "Amount must be at most ₹10,00,000."
AMOUNT_PRECISION = "Amount can have at most 2 decimal places."
CATEGORY_ERR = "Please choose a valid category."
DATE_ERR = "Please enter a valid date (YYYY-MM-DD)."
FUTURE_ERR = "Date can't be in the future."
DESC_ERR = "Description must be at most 200 characters."
DESC_CHARS_ERR = "Description can't contain line breaks or control characters."
MIN_DATE_ERR = "Date must be on or after 2000-01-01."


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _valid(**overrides):
    data = {
        "amount": "450.50",
        "category": "Food",
        "date": today_iso(),
        "description": "Dinner",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def _post(client, follow_redirects=False, **overrides):
    return client.post(
        "/expenses/add", data=_valid(**overrides), follow_redirects=follow_redirects
    )


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_with_flash(client):
    resp = client.get("/expenses/add")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert SIGN_IN_MESSAGE in page_text(client.get("/login"))


def test_signed_out_post_inserts_nothing(client):
    before = expense_count()
    resp = _post(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert expense_count() == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_cleared_and_redirected(client, method):
    with client.session_transaction() as sess:
        sess["user_id"] = 999_999
        sess["user_name"] = "Ghost"
    before = expense_count()
    resp = getattr(client, method)("/expenses/add", data=_valid() if method == "post" else None)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_data(client)
    assert expense_count() == before


# ------------------------------------------------------------------ #
# GET form                                                            #
# ------------------------------------------------------------------ #

def test_get_renders_form(client):
    login(client)
    resp = client.get("/expenses/add")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    for field in ("amount", "category", "date", "description"):
        assert f'<label for="{field}"' in body
        assert f'name="{field}"' in body
    assert 'method="post"' in body
    assert 'action="/expenses/add"' in body
    assert "novalidate" in body
    assert 'step="0.01"' in body
    assert 'type="date"' in body


def test_select_lists_all_categories(client):
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)
    values = re.findall(r'<option value="([^"]*)"', body)
    assert values == [""] + db_module.CATEGORIES
    assert re.search(r'<option value="" disabled selected>', body)


def test_date_prefilled_with_today(client):
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)
    assert f'max="{today_iso()}"' in body
    assert f'value="{today_iso()}"' in body


# ------------------------------------------------------------------ #
# Successful POST                                                     #
# ------------------------------------------------------------------ #

def test_valid_post_inserts_and_redirects(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    before = len(expense_rows(demo_id))
    resp = _post(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    rows = expense_rows(demo_id)
    assert len(rows) == before + 1
    new = rows[-1]
    assert new["amount"] == pytest.approx(450.5)
    assert new["category"] == "Food"
    assert new["date"] == today_iso()
    assert new["description"] == "Dinner"

    assert "Expense added." in page_text(client.get("/profile"))


def test_profile_reflects_new_expense(client):
    login(client)
    _post(client)
    body = page_text(client.get("/profile"))
    assert "₹7,800.50" in body  # 7,350 seeded + 450.50
    assert re.search(r'stat-label">Transactions</span>\s*<span class="stat-value">9<', body)
    assert "Dinner" in body
    assert "₹2,100.50" in body  # Food: 250 + 1,400 + 450.50


def test_empty_description_stored_null(client):
    login(client)
    _post(client, description="   ")
    row = expense_rows(user_id_for(DEMO["email"]))[-1]
    assert row["description"] is None
    assert "Expense added." in page_text(client.get("/profile"))


def test_missing_description_field_ok(client):
    login(client)
    resp = client.post("/expenses/add", data=_valid(description=None))
    assert resp.status_code == 302
    assert expense_rows(user_id_for(DEMO["email"]))[-1]["description"] is None


def test_values_normalised(client):
    login(client)
    _post(client, amount="  99.9 ", date="2026-1-5", description="  Tea  ")
    row = expense_rows(user_id_for(DEMO["email"]))[-1]
    assert row["amount"] == pytest.approx(99.9)
    assert row["date"] == "2026-01-05"
    assert row["description"] == "Tea"


@pytest.mark.parametrize("amount", ["1000000", "0.01", "12.340", "5."])
def test_boundary_amounts_accepted(client, amount):
    login(client)
    assert _post(client, amount=amount).status_code == 302


def test_boundary_description_and_today_accepted(client):
    login(client)
    resp = _post(client, description="x" * 200, date=today_iso())
    assert resp.status_code == 302


# ------------------------------------------------------------------ #
# Invalid input                                                       #
# ------------------------------------------------------------------ #

INVALID_CASES = [
    ({"amount": ""}, AMOUNT_REQUIRED),
    ({"amount": "0"}, AMOUNT_REQUIRED),
    ({"amount": "0.00"}, AMOUNT_REQUIRED),
    ({"amount": "-5"}, AMOUNT_REQUIRED),
    ({"amount": "abc"}, AMOUNT_REQUIRED),
    ({"amount": "nan"}, AMOUNT_REQUIRED),
    ({"amount": "inf"}, AMOUNT_REQUIRED),
    ({"amount": "1e2"}, AMOUNT_REQUIRED),
    ({"amount": "1_000"}, AMOUNT_REQUIRED),
    ({"amount": "12.345"}, AMOUNT_PRECISION),
    ({"amount": "1000000.01"}, AMOUNT_MAX),
    ({"amount": "2000000"}, AMOUNT_MAX),
    ({"category": "Crypto"}, CATEGORY_ERR),
    ({"category": "food"}, CATEGORY_ERR),
    ({"category": None}, CATEGORY_ERR),
    ({"date": ""}, DATE_ERR),
    ({"date": "2026-02-30"}, DATE_ERR),
    ({"date": "19/11/2026"}, DATE_ERR),
    ({"date": "0001-01-01"}, MIN_DATE_ERR),
    ({"date": "1999-12-31"}, MIN_DATE_ERR),
    ({"description": "x" * 201}, DESC_ERR),
    ({"description": "line one\nline two"}, DESC_CHARS_ERR),
    ({"description": "tab\there"}, DESC_CHARS_ERR),
    ({"description": "nul\x00byte"}, DESC_CHARS_ERR),
    ({"amount": "0" * 30 + "1"}, AMOUNT_REQUIRED),
]


@pytest.mark.parametrize("overrides, error", INVALID_CASES)
def test_invalid_input_rerenders_with_error(client, overrides, error):
    login(client)
    before = expense_count()
    resp = _post(client, **overrides)
    assert resp.status_code == 200
    assert alert_text(page_text(resp)) == error
    assert expense_count() == before


def test_future_date_rejected(client):
    login(client)
    before = expense_count()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    resp = _post(client, date=tomorrow)
    assert resp.status_code == 200
    assert alert_text(page_text(resp)) == FUTURE_ERR
    assert expense_count() == before


def test_preserves_values_on_error(client):
    login(client)
    resp = _post(client, amount="12.345", category="Health", date="2026-03-01", description="Dentist")
    body = resp.get_data(as_text=True)
    assert 'value="12.345"' in body
    assert selected_options(body) == ["Health"]
    assert 'value="2026-03-01"' in body
    assert 'value="Dentist"' in body


def test_invalid_category_keeps_placeholder_selected(client):
    login(client)
    body = _post(client, category="Crypto").get_data(as_text=True)
    assert selected_options(body) == [""]


def _form(**overrides):
    return {"amount": "10", "category": "Food", "date": "2026-03-15", "description": "", **overrides}


def test_first_invalid_field_wins():
    cleaned, error = app_module._validate_expense(_form(amount="abc", category="Crypto", date=""))
    assert cleaned is None
    assert error == AMOUNT_REQUIRED


def test_validator_future_boundary():
    fixed = date(2026, 3, 15)
    _, error = app_module._validate_expense(_form(date="2026-03-16"), today=fixed)
    assert error == FUTURE_ERR
    cleaned, error = app_module._validate_expense(_form(), today=fixed)
    assert error is None
    assert cleaned == {
        "amount": 10.0,
        "category": "Food",
        "expense_date": "2026-03-15",
        "description": None,
    }


def test_validator_min_date_boundary():
    fixed = date(2026, 3, 15)
    _, error = app_module._validate_expense(_form(date="1999-12-31"), today=fixed)
    assert error == MIN_DATE_ERR
    _, error = app_module._validate_expense(_form(date="2000-01-01"), today=fixed)
    assert error is None


@pytest.mark.parametrize("raw, expected", [("450.5", "450.50"), (".5", "0.50"), ("12.340", "12.34")])
def test_parse_amount_rounds_to_cents(raw, expected):
    value, error = app_module._parse_amount(raw)
    assert error is None
    assert str(value) == expected


def test_parse_amount_rejects_overlong_input():
    assert app_module._parse_amount("1" * 21) == (None, AMOUNT_REQUIRED)


# ------------------------------------------------------------------ #
# Security                                                            #
# ------------------------------------------------------------------ #

def test_form_user_id_ignored(client):
    demo_id = user_id_for(DEMO["email"])
    demo_before = len(expense_rows(demo_id))
    register_and_login(client, "Bea Lane", "bea@example.com")
    bea_id = user_id_for("bea@example.com")
    client.post("/expenses/add", data={**_valid(), "user_id": str(demo_id)})
    assert len(expense_rows(demo_id)) == demo_before
    assert len(expense_rows(bea_id)) == 1


def test_script_description_escaped(client):
    login(client)
    payload = "<script>alert(1)</script>"
    _post(client, description=payload)
    assert expense_rows(user_id_for(DEMO["email"]))[-1]["description"] == payload
    raw = client.get("/profile").get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in raw
    assert payload not in raw


def test_script_in_rerendered_form_escaped(client):
    login(client)
    payload = '"><script>alert(1)</script>'
    raw = _post(client, amount="", description=payload).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in raw


def test_oversized_body_rejected(client):
    login(client)
    before = expense_count()
    resp = _post(client, description="x" * (20 * 1024))
    assert resp.status_code == 413
    assert expense_count() == before


def test_unicode_description_accepted(client):
    login(client)
    _post(client, description="Chai ☕ — ₹ café")
    assert expense_rows(user_id_for(DEMO["email"]))[-1]["description"] == "Chai ☕ — ₹ café"


def test_session_cookie_samesite_lax(app):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_sql_injection_description_literal(client):
    login(client)
    payload = "'); DROP TABLE expenses;--"
    before = expense_count()
    _post(client, description=payload)
    assert expense_count() == before + 1
    assert expense_rows(user_id_for(DEMO["email"]))[-1]["description"] == payload


# ------------------------------------------------------------------ #
# DB helper                                                           #
# ------------------------------------------------------------------ #

def test_create_expense_returns_id(app):
    demo_id = user_id_for(DEMO["email"])
    new_id = db_module.create_expense(demo_id, 12.5, "Transport", "2026-01-02", "Bus")
    row = expense_rows(demo_id)[-1]
    assert row == {
        "id": new_id,
        "user_id": demo_id,
        "amount": 12.5,
        "category": "Transport",
        "date": "2026-01-02",
        "description": "Bus",
    }


def test_create_expense_description_defaults_to_null(app):
    demo_id = user_id_for(DEMO["email"])
    db_module.create_expense(demo_id, 1.0, "Other", "2026-01-02")
    assert expense_rows(demo_id)[-1]["description"] is None


def test_create_expense_unknown_user_raises(app):
    with pytest.raises(sqlite3.IntegrityError):
        db_module.create_expense(999_999, 1.0, "Other", "2026-01-02")


# ------------------------------------------------------------------ #
# Profile entry points                                                #
# ------------------------------------------------------------------ #

def test_profile_has_add_expense_link(client):
    login(client)
    body = client.get("/profile").get_data(as_text=True)
    assert re.search(r'<a href="/expenses/add"[^>]*>Add expense</a>', body)


def test_empty_state_links_to_add(client):
    register_and_login(client, "New Person", "new@example.com")
    body = client.get("/profile").get_data(as_text=True)
    assert "No transactions yet." in body
    assert re.search(r'class="profile-empty">No transactions yet\.\s*<a href="/expenses/add"', body)


def test_filtered_empty_state_has_no_add_link(client):
    register_and_login(client, "New Person", "new@example.com")
    body = client.get("/profile?start_date=2020-01-01&end_date=2020-01-31").get_data(as_text=True)
    assert '<p class="profile-empty">No transactions in this period.</p>' in body


# ------------------------------------------------------------------ #
# Static rules, regressions, docs                                     #
# ------------------------------------------------------------------ #

def test_template_rules():
    source = TEMPLATE_PATH.read_text()
    assert source.lstrip().startswith('{% extends "base.html" %}')
    assert "css/add_expense.css" in source
    assert "<style" not in source
    assert "style=" not in source
    assert "|safe" not in source
    assert 'href="/' not in source
    assert 'action="/' not in source


def test_css_no_hex_and_mobile_rules():
    css = CSS_PATH.read_text()
    assert not HEX_RE.search(css)
    assert not HEX_RE.search(PROFILE_CSS_PATH.read_text())
    mobile = css[css.index("@media (max-width: 480px)"):]
    assert ".form-actions" in mobile
    assert "flex-direction: column" in mobile


def test_edit_and_delete_implemented(client):
    # Edit and delete were stubs until Steps 8 and 9; signed out both now
    # redirect to /login.
    for url, stub in (("/expenses/1/edit", "Step 8"), ("/expenses/1/delete", "Step 9")):
        resp = client.get(url)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")
        assert f"coming in {stub}" not in resp.get_data(as_text=True)


def test_add_stub_removed(client):
    login(client)
    assert "coming in Step 7" not in client.get("/expenses/add").get_data(as_text=True)

