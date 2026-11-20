"""Tests for Step 9: deleting an expense at /expenses/<id>/delete."""

import re

import pytest

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
    user_id_for,
    expense_rows,
    expense_count,
)

TEMPLATE_PATH = PROJECT_ROOT / "templates" / "delete_expense.html"
ADD_EXPENSE_CSS = PROJECT_ROOT / "static" / "css" / "add_expense.css"
PROFILE_CSS = PROJECT_ROOT / "static" / "css" / "profile.css"
APP_PATH = PROJECT_ROOT / "app.py"
SIGN_IN_MESSAGE = "Please sign in to delete an expense."
DELETED_MESSAGE = "Expense deleted."


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _url(expense_id):
    return f"/expenses/{expense_id}/delete"


def _row(expense_id):
    """The expense row by id regardless of owner, or None."""
    conn = db_module.get_db()
    try:
        found = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        return dict(found) if found else None
    finally:
        conn.close()


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


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_with_message(client):
    expense_id = _demo_expense()
    resp = client.get(_url(expense_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert SIGN_IN_MESSAGE in page_text(client.get("/login"))


def test_signed_out_post_redirects_and_row_kept(client):
    expense_id = _demo_expense()
    before = _row(expense_id)
    resp = client.post(_url(expense_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert _row(expense_id) == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_stale_session_cleared_and_redirected(client, method):
    expense_id = _demo_expense()
    with client.session_transaction() as sess:
        sess["user_id"] = 999_999
    resp = getattr(client, method)(_url(expense_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_data(client)
    assert _row(expense_id) is not None


@pytest.mark.parametrize("method", ["get", "post"])
def test_missing_id_404(client, method):
    login(client)
    count = expense_count()
    assert getattr(client, method)(_url(999_999)).status_code == 404
    assert expense_count() == count


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("action", ["edit", "delete"])
def test_oversized_id_404_not_500(client, method, action):
    # Beyond SQLite's 64-bit INTEGER the DB driver would raise OverflowError.
    login(client)
    resp = getattr(client, method)(f"/expenses/{2**63}/{action}")
    assert resp.status_code == 404
    assert client.get(f"/expenses/{2**63 - 1}/{action}").status_code == 404


def test_get_foreign_404_no_leak(client):
    _, foreign_id = _foreign_expense()
    login(client)
    resp = client.get(_url(foreign_id))
    assert resp.status_code == 404
    body = page_text(resp)
    assert "Secret purchase" not in body
    assert "777.77" not in body


def test_post_foreign_404_row_kept(client):
    _, foreign_id = _foreign_expense()
    before = _row(foreign_id)
    login(client)
    assert client.post(_url(foreign_id)).status_code == 404
    assert _row(foreign_id) == before


# ------------------------------------------------------------------ #
# Confirmation page (GET)                                             #
# ------------------------------------------------------------------ #

def test_get_shows_confirmation(client):
    login(client)
    expense_id = _demo_expense(1234.5, "Health", "Dentist visit", when="2026-03-07")
    count = expense_count()
    resp = client.get(_url(expense_id))
    assert resp.status_code == 200
    raw = resp.get_data(as_text=True)
    body = page_text(resp)
    for text in ("Delete expense", "₹1,234.50", "Health", "7 Mar 2026", "Dentist visit"):
        assert text in body
    assert re.search(
        rf'<form[^>]*method="post"[^>]*action="/expenses/{expense_id}/delete"', raw
    )
    assert 'href="/profile"' in raw and "Cancel" in body
    assert expense_count() == count
    assert _row(expense_id) is not None


def test_get_without_description_shows_placeholder(client):
    login(client)
    expense_id = _demo_expense(description=None)
    assert "No description" in page_text(client.get(_url(expense_id)))


def test_get_never_deletes(client):
    login(client)
    expense_id = _demo_expense()
    client.get(_url(expense_id))
    client.get(_url(expense_id))
    assert _row(expense_id) is not None


def test_script_description_escaped(client):
    login(client)
    expense_id = _demo_expense(description="<script>alert(1)</script>")
    raw = client.get(_url(expense_id)).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in raw
    assert "&lt;script&gt;" in raw


# ------------------------------------------------------------------ #
# Deleting (POST)                                                     #
# ------------------------------------------------------------------ #

def test_post_deletes_only_that_row(client):
    _, foreign_id = _foreign_expense()
    login(client)
    demo_id = user_id_for(DEMO["email"])
    expense_id = _demo_expense()
    others = [r for r in expense_rows(demo_id) if r["id"] != expense_id]
    foreign_before = _row(foreign_id)
    count = expense_count()

    resp = client.post(_url(expense_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert _row(expense_id) is None
    assert expense_count() == count - 1
    assert expense_rows(demo_id) == others
    assert _row(foreign_id) == foreign_before


def test_post_flashes_deleted(client):
    login(client)
    expense_id = _demo_expense()
    resp = client.post(_url(expense_id), follow_redirects=True)
    assert resp.status_code == 200
    assert DELETED_MESSAGE in page_text(resp)


def test_profile_updates_after_delete(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    stats_before = db_module.get_expense_stats(demo_id)
    breakdown_before = db_module.get_category_breakdown(demo_id)

    expense_id = _demo_expense(12345.67, "Health", "Unique MRI scan")
    assert "Unique MRI scan" in page_text(client.get("/profile"))

    client.post(_url(expense_id))
    assert "Unique MRI scan" not in page_text(client.get("/profile"))
    assert db_module.get_expense_stats(demo_id) == stats_before
    assert db_module.get_category_breakdown(demo_id) == breakdown_before


def test_delete_only_expense_shows_empty_state(client):
    register_and_login(client, "Solo User", "solo@example.com")
    solo_id = user_id_for("solo@example.com")
    expense_id = db_module.create_expense(solo_id, 99.0, "Food", today_iso(), "Snack")
    client.post(_url(expense_id))
    assert expense_rows(solo_id) == []
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert "No transactions yet" in page_text(resp)


def test_double_submit_404(client):
    login(client)
    expense_id = _demo_expense()
    assert client.post(_url(expense_id)).status_code == 302
    count = expense_count()
    assert client.post(_url(expense_id)).status_code == 404
    assert expense_count() == count


def test_body_ids_ignored(client):
    other_id, foreign_id = _foreign_expense()
    foreign_before = _row(foreign_id)
    login(client)
    expense_id = _demo_expense()
    resp = client.post(
        _url(expense_id),
        data={"id": foreign_id, "expense_id": foreign_id, "user_id": other_id},
    )
    assert resp.status_code == 302
    assert _row(expense_id) is None
    assert _row(foreign_id) == foreign_before


# ------------------------------------------------------------------ #
# DB helper                                                           #
# ------------------------------------------------------------------ #

def test_db_delete_true(app):
    expense_id = _demo_expense()
    assert db_module.delete_expense_by_id(expense_id, user_id_for(DEMO["email"])) is True
    assert _row(expense_id) is None


def test_db_delete_wrong_user_false_keeps_row(app):
    _, foreign_id = _foreign_expense()
    before = _row(foreign_id)
    assert db_module.delete_expense_by_id(foreign_id, user_id_for(DEMO["email"])) is False
    assert _row(foreign_id) == before


def test_db_delete_missing_false(app):
    count = expense_count()
    assert db_module.delete_expense_by_id(999_999, user_id_for(DEMO["email"])) is False
    assert expense_count() == count


# ------------------------------------------------------------------ #
# Profile delete links                                                #
# ------------------------------------------------------------------ #

def test_profile_rows_have_delete_links(client):
    login(client)
    demo_id = user_id_for(DEMO["email"])
    body = client.get("/profile").get_data(as_text=True)
    shown = db_module.get_recent_expenses(demo_id)
    assert shown
    link_ids = [int(i) for i in re.findall(r'href="/expenses/(\d+)/delete"', body)]
    assert sorted(link_ids) == sorted(row["id"] for row in shown)
    assert body.count('class="txn-delete-link"') == len(shown)
    for row in shown:  # seeded descriptions contain no characters Jinja escapes
        label = f'aria-label="Delete {row["description"] or row["category"]} on {row["date"]}"'
        assert label in body


def test_delete_link_leads_to_confirmation(client):
    login(client)
    body = client.get("/profile").get_data(as_text=True)
    href = re.search(r'href="(/expenses/(\d+)/delete)"', body)
    resp = client.get(href.group(1))
    assert resp.status_code == 200
    assert _row(int(href.group(2))) is not None


# ------------------------------------------------------------------ #
# Static rules and regressions                                        #
# ------------------------------------------------------------------ #

def test_template_rules():
    source = TEMPLATE_PATH.read_text()
    assert source.lstrip().startswith('{% extends "base.html" %}')
    assert "css/add_expense.css" in source
    assert "url_for('delete_expense', id=expense.id)" in source
    assert "url_for('profile')" in source
    for rule in ("<style", "style=", "|safe", 'href="/', 'action="/', "confirm(", "<input"):
        assert rule not in source


def test_css_rules():
    add_css = ADD_EXPENSE_CSS.read_text()
    profile_css = PROFILE_CSS.read_text()
    assert not HEX_RE.search(add_css)
    assert not HEX_RE.search(profile_css)
    assert re.search(r"\.btn-danger\s*\{[^}]*var\(--danger\)", add_css)
    assert ".expense-summary" in add_css
    assert re.search(r"\.txn-delete-link\s*\{[^}]*var\(--danger\)", profile_css)
    assert re.search(r"\.table-scroll\s*\{[^}]*overflow-x:\s*auto", profile_css)


def test_no_stub_routes_remain():
    source = APP_PATH.read_text()
    assert "coming in Step" not in source
    assert "Placeholder routes" not in source
