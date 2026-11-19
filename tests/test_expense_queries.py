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


# ------------------------------------------------------------------ #
# Step 6: optional date bounds                                        #
# ------------------------------------------------------------------ #

MAR_FIRST = "2026-03-01"
MAR_MID = "2026-03-15"
MAR_LAST = "2026-03-31"
APR_FIRST = "2026-04-01"


@pytest.fixture
def dated_user(new_user):
    _add(new_user, 100, "Food", MAR_FIRST, "Mar first")
    _add(new_user, 250, "Bills", MAR_MID, "Mar mid")
    _add(new_user, 200, "Food", MAR_LAST, "Mar last")
    _add(new_user, 400, "Health", APR_FIRST, "Apr first")
    return new_user


def _descs(rows):
    return [r["description"] for r in rows]


class TestDateBoundsNoFilter:
    def test_no_bounds_matches_unfiltered_calls(self, dated_user):
        stats = db_module.get_expense_stats(dated_user)
        assert db_module.get_expense_stats(
            dated_user, start_date=None, end_date=None
        ) == stats
        assert stats == {
            "total_spent": pytest.approx(950.0),
            "transaction_count": 4,
            "top_category": "Health",
        }
        assert db_module.get_recent_expenses(
            dated_user, start_date=None, end_date=None
        ) == db_module.get_recent_expenses(dated_user)
        assert db_module.get_category_breakdown(
            dated_user, start_date=None, end_date=None
        ) == db_module.get_category_breakdown(dated_user)

    def test_demo_user_unchanged_without_bounds(self, demo_id):
        assert db_module.get_expense_stats(demo_id)["transaction_count"] == 8
        assert len(db_module.get_recent_expenses(demo_id, limit=50)) == 8


class TestDateBoundsRanges:
    def test_inclusive_boundaries_in_stats(self, dated_user):
        stats = db_module.get_expense_stats(
            dated_user, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert stats["transaction_count"] == 3
        assert stats["total_spent"] == pytest.approx(550.0)
        assert stats["top_category"] == "Food"

    def test_inclusive_boundaries_in_recent(self, dated_user):
        recent = db_module.get_recent_expenses(
            dated_user, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert _descs(recent) == ["Mar last", "Mar mid", "Mar first"]

    def test_inclusive_boundaries_in_breakdown(self, dated_user):
        breakdown = db_module.get_category_breakdown(
            dated_user, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert {c["name"]: c["amount"] for c in breakdown} == {
            "Food": pytest.approx(300.0),
            "Bills": pytest.approx(250.0),
        }

    def test_start_only_is_open_ended(self, dated_user):
        stats = db_module.get_expense_stats(dated_user, start_date=MAR_MID)
        assert stats["transaction_count"] == 3
        assert stats["total_spent"] == pytest.approx(850.0)
        recent = db_module.get_recent_expenses(dated_user, start_date=MAR_MID)
        assert _descs(recent) == ["Apr first", "Mar last", "Mar mid"]

    def test_end_only_is_open_ended(self, dated_user):
        stats = db_module.get_expense_stats(dated_user, end_date=MAR_MID)
        assert stats["transaction_count"] == 2
        assert stats["total_spent"] == pytest.approx(350.0)
        recent = db_module.get_recent_expenses(dated_user, end_date=MAR_MID)
        assert _descs(recent) == ["Mar mid", "Mar first"]

    def test_start_equal_to_end_gives_single_day(self, dated_user):
        stats = db_module.get_expense_stats(
            dated_user, start_date=MAR_MID, end_date=MAR_MID
        )
        assert stats == {
            "total_spent": pytest.approx(250.0),
            "transaction_count": 1,
            "top_category": "Bills",
        }
        recent = db_module.get_recent_expenses(
            dated_user, start_date=MAR_MID, end_date=MAR_MID
        )
        assert _descs(recent) == ["Mar mid"]

    def test_empty_range_shapes(self, dated_user):
        kwargs = {"start_date": "2026-05-01", "end_date": "2026-05-31"}
        assert db_module.get_expense_stats(dated_user, **kwargs) == {
            "total_spent": 0.0,
            "transaction_count": 0,
            "top_category": None,
        }
        assert db_module.get_recent_expenses(dated_user, **kwargs) == []
        assert db_module.get_category_breakdown(dated_user, **kwargs) == []

    def test_filtered_breakdown_sums_to_100_and_is_scoped(self, dated_user):
        breakdown = db_module.get_category_breakdown(
            dated_user, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert "Health" not in [c["name"] for c in breakdown]
        assert sum(c["percent"] for c in breakdown) == 100
        assert all(isinstance(c["percent"], int) for c in breakdown)

    def test_recent_limit_and_order_within_range(self, dated_user):
        recent = db_module.get_recent_expenses(
            dated_user, limit=2, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert _descs(recent) == ["Mar last", "Mar mid"]
        dates = [r["date"] for r in recent]
        assert dates == sorted(dates, reverse=True)

    def test_range_is_scoped_to_user(self, dated_user, demo_id):
        _add(demo_id, 5000, "Other", MAR_MID, "Demo march")
        stats = db_module.get_expense_stats(
            dated_user, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert stats["total_spent"] == pytest.approx(550.0)
        assert "Demo march" not in _descs(
            db_module.get_recent_expenses(
                dated_user, limit=50, start_date=MAR_FIRST, end_date=MAR_LAST
            )
        )
        demo_recent = db_module.get_recent_expenses(
            demo_id, limit=50, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert _descs(demo_recent) == ["Demo march"]
        demo_breakdown = db_module.get_category_breakdown(
            demo_id, start_date=MAR_FIRST, end_date=MAR_LAST
        )
        assert [(c["name"], c["percent"]) for c in demo_breakdown] == [("Other", 100)]


class TestDateRangeClause:
    def test_bound_values_go_into_params_never_sql(self):
        evil = "2026-01-01' OR '1'='1"
        sql, params = db_module._date_range_clause(7, start_date=evil, end_date=MAR_LAST)
        assert params == (7, evil, MAR_LAST)
        assert evil not in sql and MAR_LAST not in sql
