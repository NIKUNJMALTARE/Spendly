import os
import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

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

# (amount, category, day_of_month, description)
SAMPLE_EXPENSES = [
    (12.50, "Food", 2, "Lunch at cafe"),
    (45.00, "Transport", 4, "Monthly metro pass"),
    (120.00, "Bills", 7, "Electricity bill"),
    (30.25, "Health", 10, "Pharmacy"),
    (15.99, "Entertainment", 13, "Movie tickets"),
    (64.80, "Shopping", 17, "Running shoes"),
    (8.75, "Other", 21, "Gift wrapping"),
    (38.40, "Food", 25, "Weekly groceries"),
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
                (user_id, amount, category, today.replace(day=day).isoformat(), description)
                for amount, category, day, description in SAMPLE_EXPENSES
            ]
            conn.executemany(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    finally:
        conn.close()
