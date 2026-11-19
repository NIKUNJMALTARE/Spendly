"""Tests for Step 5 expense read helpers in database/db.py."""

from datetime import date, timedelta

import pytest

import database.db as db_module

DEMO_EMAIL = "demo@spendly.com"
TODAY = date.today().isoformat()


def _add(user_id, amount, category, expense_date=TODAY, description="Item"):
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


@pytest.fixture
def demo_id(app):
    return db_module.get_user_by_email(DEMO_EMAIL)["id"]


@pytest.fixture
def new_user(app):
    return db_module.create_user("Empty User", "empty@example.com", "password123")


def _percents(user_id):
    return [(c["name"], c["percent"]) for c in db_module.get_category_breakdown(user_id)]


# ------------------------------------------------------------------ #
# Demo user (seed data)                                               #
# ------------------------------------------------------------------ #

def test_demo_stats(demo_id):
    stats = db_module.get_expense_stats(demo_id)
    assert set(stats.keys()) == {"total_spent", "transaction_count", "top_category"}
    assert stats["total_spent"] == pytest.approx(7350.0)
    assert isinstance(stats["total_spent"], float)
    assert stats["transaction_count"] == 8
    assert stats["top_category"] == "Shopping"


def test_demo_recent_expenses(demo_id):
    recent = db_module.get_recent_expenses(demo_id)
    assert [r["description"] for r in recent] == [
        "Weekly groceries",
        "Gift wrapping",
        "Running shoes",
        "Movie tickets",
        "Pharmacy",
    ]
    for row in recent:
        assert set(row.keys()) == {"date", "description", "category", "amount"}
    assert recent[0]["amount"] == pytest.approx(1400.0)
    dates = [r["date"] for r in recent]
    assert dates == sorted(dates, reverse=True)


def test_demo_category_breakdown(demo_id):
    breakdown = db_module.get_category_breakdown(demo_id)
    assert _percents(demo_id) == [
        ("Shopping", 30),
        ("Bills", 25),
        ("Food", 22),
        ("Transport", 8),
        ("Entertainment", 7),
        ("Health", 6),
        ("Other", 2),
    ]
    for item in breakdown:
        assert set(item.keys()) == {"name", "amount", "percent"}
        assert isinstance(item["percent"], int)
    assert breakdown[2]["amount"] == pytest.approx(1650.0)  # Food: 250 + 1400


def test_seed_dates_not_in_future_and_amounts_realistic(demo_id):
    conn = db_module.get_db()
    try:
        rows = conn.execute(
            "SELECT amount, date FROM expenses WHERE user_id = ?", (demo_id,)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 8
    oldest_allowed = (date.today() - timedelta(days=31)).isoformat()
    for row in rows:
        assert oldest_allowed <= row["date"] <= TODAY
        assert row["amount"] >= 100  # rupee-sized, not the old dollar amounts


# ------------------------------------------------------------------ #
# Empty user                                                          #
# ------------------------------------------------------------------ #

def test_empty_user(new_user):
    assert db_module.get_expense_stats(new_user) == {
        "total_spent": 0.0,
        "transaction_count": 0,
        "top_category": None,
    }
    assert db_module.get_recent_expenses(new_user) == []
    assert db_module.get_category_breakdown(new_user) == []


# ------------------------------------------------------------------ #
# Recent expenses                                                     #
# ------------------------------------------------------------------ #

def test_recent_respects_limit(demo_id):
    assert len(db_module.get_recent_expenses(demo_id, limit=2)) == 2
    assert len(db_module.get_recent_expenses(demo_id, limit=50)) == 8


def test_same_date_newest_id_first(new_user):
    _add(new_user, 100, "Food", TODAY, "First added")
    _add(new_user, 100, "Food", TODAY, "Second added")
    recent = db_module.get_recent_expenses(new_user)
    assert [r["description"] for r in recent] == ["Second added", "First added"]


def test_null_description_becomes_empty_string(new_user):
    _add(new_user, 100, "Other", TODAY, None)
    assert db_module.get_recent_expenses(new_user)[0]["description"] == ""


# ------------------------------------------------------------------ #
# Rounding and ties                                                   #
# ------------------------------------------------------------------ #

def test_three_equal_categories_sum_to_100(new_user):
    for category in ("Food", "Health", "Bills"):
        _add(new_user, 100, category)
    assert _percents(new_user) == [("Bills", 34), ("Food", 33), ("Health", 33)]


def test_awkward_split_sums_to_100(new_user):
    amounts = {"Food": 100.01, "Bills": 200, "Health": 300.33, "Other": 0.5}
    for category, amount in amounts.items():
        _add(new_user, amount, category)
    breakdown = db_module.get_category_breakdown(new_user)
    total = sum(amounts.values())
    assert sum(c["percent"] for c in breakdown) == 100
    for item in breakdown:
        assert isinstance(item["percent"], int)
        assert abs(item["percent"] - amounts[item["name"]] / total * 100) < 1
        assert item["amount"] == round(amounts[item["name"]], 2)


def test_seven_equal_categories(new_user):
    for category in db_module.CATEGORIES:
        _add(new_user, 50, category)
    percents = [p for _, p in _percents(new_user)]
    assert sum(percents) == 100
    assert percents == [15, 15, 14, 14, 14, 14, 14]


def test_top_category_tie_goes_alphabetically_first(new_user):
    _add(new_user, 0.1, "Food")
    _add(new_user, 0.2, "Food")
    _add(new_user, 0.3, "Bills")  # float sum 0.1 + 0.2 != 0.3 without rounding
    assert db_module.get_expense_stats(new_user)["top_category"] == "Bills"


# ------------------------------------------------------------------ #
# Isolation                                                           #
# ------------------------------------------------------------------ #

def test_helpers_only_see_own_user(demo_id, new_user):
    _add(new_user, 999, "Health", TODAY, "Other user's expense")

    demo_stats = db_module.get_expense_stats(demo_id)
    assert demo_stats["transaction_count"] == 8
    assert demo_stats["total_spent"] == pytest.approx(7350.0)
    assert "Other user's expense" not in [
        r["description"] for r in db_module.get_recent_expenses(demo_id, limit=50)
    ]

    assert db_module.get_expense_stats(new_user) == {
        "total_spent": 999.0,
        "transaction_count": 1,
        "top_category": "Health",
    }
    assert _percents(new_user) == [("Health", 100)]
