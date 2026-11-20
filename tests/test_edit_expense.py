"""Tests for Step 8: editing an expense at /expenses/<id>/edit."""

import re
from datetime import date, timedelta

import pytest

import database.db as db_module
from tests.helpers import (
    PROJECT_ROOT,
    DEMO,
    today_iso,
    login,
    page_text,
    session_data,
    alert_text,
    selected_options,
    user_id_for,
    expense_rows,
    expense_count,
)

TEMPLATE_PATH = PROJECT_ROOT / "templates" / "edit_expense.html"
FORM_PARTIAL_PATH = PROJECT_ROOT / "templates" / "_expense_form.html"
SIGN_IN_MESSAGE = "Please sign in to edit an expense."
UPDATED_MESSAGE = "Expense updated."

AMOUNT_REQUIRED = "Please enter an amount greater than zero."
AMOUNT_MAX = "Amount must be at most ₹10,00,000."
AMOUNT_PRECISION = "Amount can have at most 2 decimal places."
CATEGORY_ERR = "Please choose a valid category."
DATE_ERR = "Please enter a valid date (YYYY-MM-DD)."
FUTURE_ERR = "Date can't be in the future."
DESC_ERR = "Description must be at most 200 characters."


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _row(expense_id):
    conn = db_module.get_db()
    try:
        found = conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        return dict(found) if found else None
    finally:
        conn.close()


def _valid(**overrides):
    data = {
        "amount": "100.00",
        "category": "Shopping",
        "date": today_iso(),
        "description": "Edited",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def _demo_expense(amount=450.50, category="Food", description="Dinner", when=None):
    """Create a known expense owned by the demo user and return its id."""
    return db_module.create_expense(
        user_id_for(DEMO["email"]), amount, category, when or today_iso(), description
    )


def _foreign_expense(description="Secret purchase", amount=777.77):
    """Create an expense owned by a different user and return (user_id, id)."""
    other_id = db_module.create_user("Other Person", "other@example.com", "password123")
    expense_id = db_module.create_expense(
        other_id, amount, "Health", "2026-01-10", description
    )
    return other_id, expense_id


def _url(expense_id):
    return f"/expenses/{expense_id}/edit"


def _post(client, expense_id, follow_redirects=False, **overrides):
    return client.post(
        _url(expense_id),
        data=_valid(**overrides),
        follow_redirects=follow_redirects,
    )


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_with_flash(client):
    expense_id = _demo_expense()
    resp = client.get(_url(expense_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert SIGN_IN_MESSAGE in page_text(client.get("/login"))


def test_signed_out_post_redirects_and_row_unchanged(client):
    expense_id = _demo_expense()
    before = _row(expense_id)
    resp = _post(client, expense_id)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert _row(expense_id) == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_cleared_and_redirected(client, method):
    expense_id = _demo_expense()
    before = _row(expense_id)
    with client.session_transaction() as sess:
        sess["user_id"] = 999_999
        sess["user_name"] = "Ghost"
    resp = getattr(client, method)(
        _url(expense_id), data=_valid() if method == "post" else None
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_data(client)
    assert _row(expense_id) == before


# ------------------------------------------------------------------ #
# GET form                                                            #
# ------------------------------------------------------------------ #

def test_get_own_expense_prefilled(client):
    login(client)
    expense_id = _demo_expense(450.50, "Food", "Dinner", "2026-03-05")
    resp = client.get(_url(expense_id))
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'value="450.50"' in body
    assert selected_options(body) == ["Food"]
    assert 'value="2026-03-05"' in body
    assert 'value="Dinner"' in body


def test_get_renders_form_structure(client):
    login(client)
    expense_id = _demo_expense()
    body = client.get(_url(expense_id)).get_data(as_text=True)
    for field in ("amount", "category", "date", "description"):
        assert f'<label for="{field}"' in body
        assert f'name="{field}"' in body
    assert 'method="post"' in body
    assert f'action="{_url(expense_id)}"' in body
    assert "novalidate" in body
    assert 'step="0.01"' in body
    assert f'max="{today_iso()}"' in body
    assert "Save changes" in body
    assert "Edit expense" in body
    assert 'href="/profile"' in body


def test_get_select_lists_all_categories(client):
    login(client)
    body = client.get(_url(_demo_expense())).get_data(as_text=True)
    values = re.findall(r'<option value="([^"]*)"', body)
    assert values == [""] + db_module.CATEGORIES


def test_get_null_description_shows_empty(client):
    login(client)
    expense_id = _demo_expense(description=None)
    body = client.get(_url(expense_id)).get_data(as_text=True)
    assert 'name="description"' in body
    assert "None" not in body
    assert re.search(r'name="description"[^>]*value=""', body, re.S)


def test_get_amount_has_no_thousands_separator(client):
    login(client)
    expense_id = _demo_expense(amount=1234.5)
    body = client.get(_url(expense_id)).get_data(as_text=True)
    assert 'value="1234.50"' in body


def test_get_nonexistent_id_returns_404(client):
    login(client)
    assert client.get(_url(999_999)).status_code == 404


def test_post_nonexistent_id_returns_404(client):
    login(client)
    before = expense_count()
    assert _post(client, 999_999).status_code == 404
    assert expense_count() == before


# ------------------------------------------------------------------ #
# Ownership                                                           #
# ------------------------------------------------------------------ #

def test_get_foreign_expense_returns_404_without_leaking(client):
    _, foreign_id = _foreign_expense("Secret purchase", 777.77)
    login(client)
    resp = client.get(_url(foreign_id))
    assert resp.status_code == 404
    body = page_text(resp)
    assert "Secret purchase" not in body
    assert "777.77" not in body


def test_post_foreign_expense_returns_404_and_row_unchanged(client):
    _, foreign_id = _foreign_expense()
    before = _row(foreign_id)
    login(client)
    resp = _post(client, foreign_id)
    assert resp.status_code == 404
    assert _row(foreign_id) == before


def test_foreign_invalid_post_is_404_not_validation_error(client):
    _, foreign_id = _foreign_expense()
    login(client)
    assert _post(client, foreign_id, amount="abc").status_code == 404


def test_edit_does_not_affect_other_users_rows(client):
    other_id, foreign_id = _foreign_expense()
    expense_id = _demo_expense()
    foreign_before = expense_rows(other_id)
    login(client)
    _post(client, expense_id)
    assert expense_rows(other_id) == foreign_before


# ------------------------------------------------------------------ #
# Successful POST                                                     #
# ------------------------------------------------------------------ #

def test_valid_post_updates_exactly_that_row(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    expense_id = _demo_expense()
    others_before = [r for r in expense_rows(demo_id) if r["id"] != expense_id]
    count_before = expense_count()

    resp = _post(
        client,
        expense_id,
        amount="99.90",
        category="Transport",
        date="2026-02-03",
        description="Cab",
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    row = _row(expense_id)
    assert row["amount"] == pytest.approx(99.9)
    assert row["category"] == "Transport"
    assert row["date"] == "2026-02-03"
    assert row["description"] == "Cab"
    assert expense_count() == count_before
    assert [r for r in expense_rows(demo_id) if r["id"] != expense_id] == others_before


def test_valid_post_keeps_user_id_and_created_at(client):
    login(client)
    expense_id = _demo_expense()
    before = _row(expense_id)
    _post(client, expense_id, amount="5", category="Other")
    after = _row(expense_id)
    assert after["user_id"] == before["user_id"]
    assert after["created_at"] == before["created_at"]


def test_valid_post_flashes_updated_message(client):
    login(client)
    expense_id = _demo_expense()
    resp = _post(client, expense_id, follow_redirects=True)
    assert resp.status_code == 200
    assert UPDATED_MESSAGE in page_text(resp)


def test_profile_reflects_edit(client):
    login(client)
    expense_id = _demo_expense(450.50, "Food", "Dinner")
    _post(
        client,
        expense_id,
        amount="100",
        category="Shopping",
        description="Headphones",
    )
    body = page_text(client.get("/profile"))
    assert "Headphones" in body
    assert "Dinner" not in body
    assert "₹7,450.00" in body  # 7,350 seeded + 100
    assert re.search(
        r'stat-label">Transactions</span>\s*<span class="stat-value">9<', body
    )
    assert "₹2,300.00" in body  # Shopping: 2,200 + 100
    assert "₹1,650.00" in body  # Food back to seeded 250 + 1,400


def test_clearing_description_stores_null(client):
    login(client)
    expense_id = _demo_expense(description="Dinner")
    resp = _post(client, expense_id, description="   ")
    assert resp.status_code == 302
    assert _row(expense_id)["description"] is None


def test_missing_description_field_stores_null(client):
    login(client)
    expense_id = _demo_expense(description="Dinner")
    resp = client.post(_url(expense_id), data=_valid(description=None))
    assert resp.status_code == 302
    assert _row(expense_id)["description"] is None


# ------------------------------------------------------------------ #
# Invalid input                                                       #
# ------------------------------------------------------------------ #

INVALID_CASES = [
    ({"amount": ""}, AMOUNT_REQUIRED),
    ({"amount": "0"}, AMOUNT_REQUIRED),
    ({"amount": "-5"}, AMOUNT_REQUIRED),
    ({"amount": "abc"}, AMOUNT_REQUIRED),
    ({"amount": "nan"}, AMOUNT_REQUIRED),
    ({"amount": "12.345"}, AMOUNT_PRECISION),
    ({"amount": "1000000.01"}, AMOUNT_MAX),
    ({"amount": "2000000"}, AMOUNT_MAX),
    ({"category": "Crypto"}, CATEGORY_ERR),
    ({"category": None}, CATEGORY_ERR),
    ({"date": ""}, DATE_ERR),
    ({"date": None}, DATE_ERR),
    ({"date": "2026-02-30"}, DATE_ERR),
    ({"description": "x" * 201}, DESC_ERR),
]


@pytest.mark.parametrize("overrides, error", INVALID_CASES)
def test_invalid_input_rerenders_with_error_and_row_unchanged(client, overrides, error):
    login(client)
    expense_id = _demo_expense()
    before = _row(expense_id)
    resp = _post(client, expense_id, **overrides)
    assert resp.status_code == 200
    assert alert_text(page_text(resp)) == error
    assert _row(expense_id) == before


def test_future_date_rejected_row_unchanged(client):
    login(client)
    expense_id = _demo_expense()
    before = _row(expense_id)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    resp = _post(client, expense_id, date=tomorrow)
    assert resp.status_code == 200
    assert alert_text(page_text(resp)) == FUTURE_ERR
    assert _row(expense_id) == before


def test_invalid_post_shows_submitted_not_stored_values(client):
    login(client)
    expense_id = _demo_expense(450.50, "Food", "Dinner", "2026-03-05")
    resp = _post(
        client,
        expense_id,
        amount="12.345",
        category="Health",
        date="2026-03-01",
        description="Dentist",
    )
    body = resp.get_data(as_text=True)
    assert 'value="12.345"' in body
    assert selected_options(body) == ["Health"]
    assert 'value="2026-03-01"' in body
    assert 'value="Dentist"' in body
    assert 'value="450.50"' not in body
    assert 'value="Dinner"' not in body


def test_invalid_post_form_still_posts_to_same_url(client):
    login(client)
    expense_id = _demo_expense()
    body = _post(client, expense_id, amount="abc").get_data(as_text=True)
    assert f'action="{_url(expense_id)}"' in body


# ------------------------------------------------------------------ #
# Security                                                            #
# ------------------------------------------------------------------ #

def test_body_user_id_and_ids_ignored(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    other_id = db_module.create_user("Other Person", "other@example.com", "password123")
    other_expense = db_module.create_expense(other_id, 10.0, "Other", "2026-01-10", "Theirs")
    expense_id = _demo_expense()
    other_before = _row(other_expense)

    resp = client.post(
        _url(expense_id),
        data={
            **_valid(amount="55"),
            "user_id": str(other_id),
            "id": str(other_expense),
            "expense_id": str(other_expense),
        },
    )
    assert resp.status_code == 302
    updated = _row(expense_id)
    assert updated["user_id"] == demo_id
    assert updated["amount"] == pytest.approx(55.0)
    assert _row(other_expense) == other_before


def test_script_description_escaped_on_form_and_profile(client):
    login(client)
    payload = "<script>alert(1)</script>"
    expense_id = _demo_expense()
    _post(client, expense_id, description=payload)
    assert _row(expense_id)["description"] == payload

    profile_raw = client.get("/profile").get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in profile_raw
    assert payload not in profile_raw

    form_raw = client.get(_url(expense_id)).get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in form_raw
    assert payload not in form_raw


def test_sql_injection_description_stored_literally(client):
    login(client)
    expense_id = _demo_expense()
    payload = "'); DROP TABLE expenses;--"
    before = expense_count()
    assert _post(client, expense_id, description=payload).status_code == 302
    assert expense_count() == before
    assert _row(expense_id)["description"] == payload


# ------------------------------------------------------------------ #
# DB helpers                                                          #
# ------------------------------------------------------------------ #

def test_get_expense_by_id_returns_owned_row(app):
    demo_id = user_id_for(DEMO["email"])
    expense_id = db_module.create_expense(demo_id, 450.5, "Food", "2026-03-05", "Dinner")
    found = db_module.get_expense_by_id(expense_id, demo_id)
    assert found["id"] == expense_id
    assert found["user_id"] == demo_id
    assert found["amount"] == pytest.approx(450.5)
    assert found["category"] == "Food"
    assert found["date"] == "2026-03-05"
    assert found["description"] == "Dinner"


def test_get_expense_by_id_wrong_user_returns_none(app):
    other_id, foreign_id = _foreign_expense()
    demo_id = user_id_for(DEMO["email"])
    assert db_module.get_expense_by_id(foreign_id, demo_id) is None
    assert db_module.get_expense_by_id(foreign_id, other_id) is not None


def test_get_expense_by_id_missing_returns_none(app):
    assert db_module.get_expense_by_id(999_999, user_id_for(DEMO["email"])) is None


def test_update_expense_success_returns_true(app):
    demo_id = user_id_for(DEMO["email"])
    expense_id = db_module.create_expense(demo_id, 10.0, "Food", "2026-03-05", "Old")
    before = _row(expense_id)
    assert db_module.update_expense(expense_id, demo_id, 20.5, "Bills", "2026-03-06", "New") is True
    after = _row(expense_id)
    assert after["amount"] == pytest.approx(20.5)
    assert after["category"] == "Bills"
    assert after["date"] == "2026-03-06"
    assert after["description"] == "New"
    assert after["user_id"] == before["user_id"]
    assert after["created_at"] == before["created_at"]


def test_update_expense_description_defaults_to_null(app):
    demo_id = user_id_for(DEMO["email"])
    expense_id = db_module.create_expense(demo_id, 10.0, "Food", "2026-03-05", "Old")
    assert db_module.update_expense(expense_id, demo_id, 10.0, "Food", "2026-03-05") is True
    assert _row(expense_id)["description"] is None


def test_update_expense_wrong_user_returns_false_and_changes_nothing(app):
    _, foreign_id = _foreign_expense()
    before = _row(foreign_id)
    demo_id = user_id_for(DEMO["email"])
    assert db_module.update_expense(foreign_id, demo_id, 1.0, "Other", "2026-01-01", "Hacked") is False
    assert _row(foreign_id) == before


def test_update_expense_missing_id_returns_false(app):
    demo_id = user_id_for(DEMO["email"])
    before = expense_count()
    assert db_module.update_expense(999_999, demo_id, 1.0, "Other", "2026-01-01", "x") is False
    assert expense_count() == before


def test_get_recent_expenses_rows_include_id(app):
    demo_id = user_id_for(DEMO["email"])
    rows = db_module.get_recent_expenses(demo_id, limit=50)
    assert rows
    assert all("id" in row.keys() for row in rows)
    assert {row["id"] for row in rows} == {r["id"] for r in expense_rows(demo_id)}


# ------------------------------------------------------------------ #
# Profile edit links                                                  #
# ------------------------------------------------------------------ #

def test_profile_rows_have_edit_links(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    body = client.get("/profile").get_data(as_text=True)
    shown = db_module.get_recent_expenses(demo_id)
    assert shown
    link_ids = [int(i) for i in re.findall(r'href="/expenses/(\d+)/edit"', body)]
    assert sorted(link_ids) == sorted(row["id"] for row in shown)
    assert body.count('class="txn-edit-link"') == len(shown)


def test_profile_edit_link_for_new_expense(client):
    login(client)
    expense_id = _demo_expense()
    body = client.get("/profile").get_data(as_text=True)
    assert f'href="/expenses/{expense_id}/edit"' in body


def test_profile_edit_link_ignores_date_filter_query(client):
    login(client)
    body = client.get("/profile?start_date=2020-01-01&end_date=2030-01-01").get_data(as_text=True)
    for href in re.findall(r'href="(/expenses/\d+/edit[^"]*)"', body):
        assert "?" not in href


def test_edit_link_leads_to_working_form(client):
    login(client)
    body = client.get("/profile").get_data(as_text=True)
    href = re.search(r'href="(/expenses/\d+/edit)"', body).group(1)
    assert client.get(href).status_code == 200


# ------------------------------------------------------------------ #
# Static rules and regressions                                        #
# ------------------------------------------------------------------ #

def test_template_rules():
    source = TEMPLATE_PATH.read_text()
    assert source.lstrip().startswith('{% extends "base.html" %}')
    assert "css/add_expense.css" in source
    assert "url_for('edit_expense', id=expense_id)" in source
    assert '{% include "_expense_form.html" %}' in source
    assert "<style" not in source
    assert "|safe" not in source
    assert 'href="/' not in source
    assert 'action="/' not in source


def test_shared_form_partial_rules():
    source = FORM_PARTIAL_PATH.read_text()
    assert "{% extends" not in source  # a fragment, not a page
    assert 'action="{{ form_action }}"' in source
    assert "{{ submit_label }}" in source
    assert "url_for('profile')" in source
    for rule in ("<style", "style=", "|safe", 'href="/', 'action="/'):
        assert rule not in source


def test_delete_stub_unchanged(client):
    resp = client.get("/expenses/1/delete")
    assert resp.get_data(as_text=True) == "Delete expense — coming in Step 9"

