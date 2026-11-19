import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for

from database.db import (
    create_user,
    get_category_breakdown,
    get_db,
    get_expense_stats,
    get_recent_expenses,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
    verify_user,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY", "dev-only-insecure-key")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

DUPLICATE_EMAIL_ERROR = "An account with that email already exists."
MIN_PASSWORD_LENGTH = 8
LOGIN_MISSING_FIELDS_ERROR = "Please enter your email and password."
INVALID_CREDENTIALS_ERROR = "Invalid email or password."
PROFILE_SIGN_IN_MESSAGE = "Please sign in to view your profile."

@app.template_filter("month_year")
def _format_month_year(timestamp):
    """'2026-11-18 10:00:00' -> 'November 2026'; None if missing or malformed."""
    if not timestamp:
        return None
    try:
        return datetime.strptime(str(timestamp)[:10], "%Y-%m-%d").strftime("%B %Y")
    except ValueError:
        return None


@app.template_filter("inr")
def _format_inr(amount):
    """1234.5 -> '₹1,234.50'."""
    return f"₹{amount:,.2f}"


def _validate_registration(name, email, password):
    """Return an error message for the first invalid field, or None."""
    if not name:
        return "Please enter your name."
    local, at, domain = email.partition("@")
    if not at or not local or "@" in domain or "." not in domain:
        return "Please enter a valid email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def _validate_login(email, password):
    """Return an error if a required field is empty, or None.

    No format or length checks — existing accounts (e.g. the seeded demo
    user) may predate the registration rules.
    """
    if not email or not password:
        return LOGIN_MISSING_FIELDS_ERROR
    return None


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = _validate_registration(name, email, password)
    if error is None and get_user_by_email(email) is not None:
        error = DUPLICATE_EMAIL_ERROR
    if error is None:
        try:
            create_user(name, email, password)
        except sqlite3.IntegrityError:  # same email inserted concurrently
            error = DUPLICATE_EMAIL_ERROR

    if error:
        return render_template("register.html", error=error, name=name, email=email)

    flash("Account created — please sign in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")  # never strip passwords

    error = _validate_login(email, password)
    user = None
    if error is None:
        user = verify_user(email, password)
        if user is None:
            error = INVALID_CREDENTIALS_ERROR

    if error:
        return render_template("login.html", error=error, email=email)

    session.clear()  # prevent session fixation; must run before flash()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    flash(f"Welcome back, {user['name']}!", "success")
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "success")  # after clear(), or it is wiped
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    user_id = session.get("user_id")
    if not user_id:
        flash(PROFILE_SIGN_IN_MESSAGE, "error")
        return redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if user is None:  # account removed while the session was still live
        session.clear()
        flash(PROFILE_SIGN_IN_MESSAGE, "error")  # after clear(), or it is wiped
        return redirect(url_for("login"))

    return render_template(
        "profile.html",
        user=user,
        stats=get_expense_stats(user["id"]),
        recent_transactions=get_recent_expenses(user["id"]),
        category_breakdown=get_category_breakdown(user["id"]),
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
