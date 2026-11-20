import os
import sqlite3
from datetime import date, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get(
    "SPENDLY_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "expense_tracker.db",
    ),
)

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    date        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

# (amount, category, days_ago, description) — rupee amounts; each date is
# today minus days_ago, so the demo data never lands in the future.
SAMPLE_EXPENSES = [
    (250.00, "Food", 26, "Lunch at cafe"),
    (600.00, "Transport", 24, "Monthly metro pass"),
    (1800.00, "Bills", 21, "Electricity bill"),
    (450.00, "Health", 18, "Pharmacy"),
    (500.00, "Entertainment", 14, "Movie tickets"),
    (2200.00, "Shopping", 10, "Running shoes"),
    (150.00, "Other", 6, "Gift wrapping"),
    (1400.00, "Food", 2, "Weekly groceries"),
]


def get_db():
    """Return a SQLite connection with dict-like rows and FK enforcement on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_user_by_email(email):
    """Return the users row for an (already normalised) email, or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, name, email, password_hash, created_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Return id, name, email, created_at for a user id, or None. Never the hash."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def _date_range_clause(user_id, start_date=None, end_date=None):
    """Return (where_sql, params) for a user's expenses within optional inclusive bounds.

    Only fixed SQL fragments are concatenated; every value goes through a ? placeholder.
    """
    sql = "WHERE user_id = ?"
    params = [user_id]
    if start_date is not None:
        sql += " AND date >= ?"
        params.append(start_date)
    if end_date is not None:
        sql += " AND date <= ?"
        params.append(end_date)
    return sql, tuple(params)


def get_expense_stats(user_id, start_date=None, end_date=None):
    """Return total_spent, transaction_count and top_category for a user.

    Optional start_date / end_date ('YYYY-MM-DD') limit the range, inclusive.
    """
    where, params = _date_range_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        totals = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent, "
            "COUNT(*) AS transaction_count "
            "FROM expenses " + where,
            params,
        ).fetchone()
        top = conn.execute(
            "SELECT category FROM expenses " + where + " "
            "GROUP BY category "
            "ORDER BY ROUND(SUM(amount), 2) DESC, category ASC "
            "LIMIT 1",
            params,
        ).fetchone()
        return {
            "total_spent": float(totals["total_spent"]),
            "transaction_count": int(totals["transaction_count"]),
            "top_category": top["category"] if top else None,
        }
    finally:
        conn.close()


def get_recent_expenses(user_id, limit=5, start_date=None, end_date=None):
    """Return a user's newest expenses (date, then id, descending) as dicts.

    Optional start_date / end_date ('YYYY-MM-DD') limit the range, inclusive.
    """
    where, params = _date_range_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, date, COALESCE(description, '') AS description, "
            "category, amount "
            "FROM expenses " + where + " "
            "ORDER BY date DESC, id DESC "
            "LIMIT ?",
            params + (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_category_breakdown(user_id, start_date=None, end_date=None):
    """Return per-category name, amount and whole percent (summing to 100).

    Percents use the largest-remainder method on integer paise; a user with
    no spending gets 0 for every entry. Optional start_date / end_date
    ('YYYY-MM-DD') limit the range, inclusive.
    """
    where, params = _date_range_clause(user_id, start_date, end_date)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category AS name, SUM(amount) AS amount "
            "FROM expenses " + where + " "
            "GROUP BY category "
            "ORDER BY ROUND(SUM(amount), 2) DESC, category ASC",
            params,
        ).fetchall()
    finally:
        conn.close()

    paise = [round(row["amount"] * 100) for row in rows]
    total = sum(paise)
    if total == 0:
        percents = [0] * len(rows)
    else:
        percents = [p * 100 // total for p in paise]
        remainders = [p * 100 % total for p in paise]
        leftover = 100 - sum(percents)
        by_remainder = sorted(range(len(rows)), key=lambda i: -remainders[i])
        for i in by_remainder[:leftover]:
            percents[i] += 1

    return [
        {
            "name": row["name"],
            "amount": round(row["amount"], 2),
            "percent": percent,
        }
        for row, percent in zip(rows, percents)
    ]


# Checked against when the email is unknown so that the response time
# matches a wrong-password attempt (avoids leaking which emails exist).
_DUMMY_PASSWORD_HASH = generate_password_hash("spendly-timing-equaliser")


def verify_user(email, password):
    """Return the users row if the (normalised) email and password match, else None."""
    user = get_user_by_email(email)
    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def create_user(name, email, password):
    """Insert a user with a hashed password and return the new id.

    Raises sqlite3.IntegrityError if the email is already registered.
    """
    conn = get_db()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
        return cursor.lastrowid
    finally:
        conn.close()


def create_expense(user_id, amount, category, expense_date, description=None):
    """Insert one expense for a user and return the new id.

    expense_date is a normalised 'YYYY-MM-DD' string. Raises
    sqlite3.IntegrityError if user_id doesn't exist (FKs are on).
    """
    conn = get_db()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, category, expense_date, description),
            )
        return cursor.lastrowid
    finally:
        conn.close()


def get_expense_by_id(expense_id, user_id):
    """Return one expense as a dict if it belongs to user_id, else None.

    A missing id and another user's id look the same to the caller.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_expense(
    expense_id, user_id, amount, category, expense_date, description=None
):
    """Update one of user_id's expenses; return True if exactly one row changed.

    Ownership is enforced in the WHERE clause, so a wrong user or a missing
    id changes nothing and returns False. user_id and created_at are never
    written.
    """
    conn = get_db()
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE expenses "
                "SET amount = ?, category = ?, date = ?, description = ? "
                "WHERE id = ? AND user_id = ?",
                (amount, category, expense_date, description, expense_id, user_id),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def delete_expense_by_id(expense_id, user_id):
    """Delete one of user_id's expenses; return True if exactly one row went.

    Ownership is enforced in the WHERE clause, so a wrong user or a missing
    id deletes nothing and returns False. Nothing references expenses.id,
    so no cascade is needed.
    """
    conn = get_db()
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, user_id),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist. Safe to call repeatedly."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def seed_db():
    """Insert a demo user and sample expenses, only if no users exist yet."""
    conn = get_db()
    try:
        with conn:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if user_count > 0:
                return

            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
            )
            user_id = cursor.lastrowid

            today = date.today()
            rows = [
                (
                    user_id,
                    amount,
                    category,
                    (today - timedelta(days=days_ago)).isoformat(),
                    description,
                )
                for amount, category, days_ago, description in SAMPLE_EXPENSES
            ]
            conn.executemany(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    finally:
        conn.close()
