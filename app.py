import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db import (
    CATEGORIES,
    create_expense,
    create_user,
    get_category_breakdown,
    get_db,
    get_expense_by_id,
    get_expense_stats,
    get_recent_expenses,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
    update_expense,
    verify_user,
)

app = Flask(__name__)
# Without SPENDLY_SECRET_KEY, use a random per-process key: sessions don't
# survive a restart, but there is no well-known key to forge sessions with.
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024,  # every form here is tiny; larger bodies get a 413
    SESSION_COOKIE_SAMESITE="Lax",  # partial CSRF mitigation until real tokens exist
)

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
ANALYTICS_SIGN_IN_MESSAGE = "Please sign in to view analytics."
DATE_FORMAT_ERROR = "Please enter valid dates (YYYY-MM-DD)."
DATE_ORDER_ERROR = "Start date must be on or before end date."
DATE_INPUT_FORMAT = "%Y-%m-%d"  # what <input type="date"> submits and the DB stores
LAST_N_DAYS = 30  # "Last 30 days" preset, counting today

ADD_EXPENSE_SIGN_IN_MESSAGE = "Please sign in to add an expense."
EXPENSE_ADDED_MESSAGE = "Expense added."
EDIT_EXPENSE_SIGN_IN_MESSAGE = "Please sign in to edit an expense."
EXPENSE_UPDATED_MESSAGE = "Expense updated."
MAX_EXPENSE_AMOUNT = Decimal("1000000")
MAX_AMOUNT_INPUT_LENGTH = 20  # longer than any valid amount; checked before the regex
MAX_DESCRIPTION_LENGTH = 200
MIN_EXPENSE_DATE = date(2000, 1, 1)
CENTS = Decimal("0.01")
# Plain decimals only, e.g. "450", "450.5", ".5". Rejects "-5", "1e2", "nan",
# "inf", "1_000" and non-ASCII digits.
AMOUNT_RE = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")
AMOUNT_REQUIRED_ERROR = "Please enter an amount greater than zero."
AMOUNT_MAX_ERROR = "Amount must be at most ₹10,00,000."
AMOUNT_PRECISION_ERROR = "Amount can have at most 2 decimal places."
CATEGORY_ERROR = "Please choose a valid category."
EXPENSE_DATE_ERROR = "Please enter a valid date (YYYY-MM-DD)."
FUTURE_DATE_ERROR = "Date can't be in the future."
MIN_DATE_ERROR = f"Date must be on or after {MIN_EXPENSE_DATE.year}-01-01."
DESCRIPTION_LENGTH_ERROR = (
    f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters."
)
DESCRIPTION_CHARS_ERROR = "Description can't contain line breaks or control characters."
EXPENSE_FIELDS = ("amount", "category", "date", "description")


@app.template_filter("month_year")
def _format_month_year(timestamp):
    """'2026-11-18 10:00:00' -> 'November 2026'; None if missing or malformed."""
    if not timestamp:
        return None
    try:
        return datetime.strptime(str(timestamp)[:10], "%Y-%m-%d").strftime("%B %Y")
    except ValueError:
        return None


@app.template_filter("short_date")
def _format_short_date(value):
    """'2026-11-01' -> '1 Nov 2026'; None if missing or malformed."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(str(value)[:10], DATE_INPUT_FORMAT)
    except ValueError:
        return None
    # parsed.day, not "%-d": strftime's no-padding flag isn't portable (fails on Windows).
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


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


def _parse_amount(raw):
    """Return (Decimal rounded to 2 dp, None), or (None, error)."""
    if len(raw) > MAX_AMOUNT_INPUT_LENGTH or not AMOUNT_RE.fullmatch(raw):
        return None, AMOUNT_REQUIRED_ERROR
    value = Decimal(raw)  # can't raise: the regex only admits plain decimals
    if value <= 0:
        return None, AMOUNT_REQUIRED_ERROR
    if value > MAX_EXPENSE_AMOUNT:  # before quantize, which needs bounded precision
        return None, AMOUNT_MAX_ERROR
    if value != value.quantize(CENTS):
        return None, AMOUNT_PRECISION_ERROR
    return value.quantize(CENTS), None


def _validate_expense(form, today=None):
    """Return (cleaned, None), or (None, error) for the first invalid field.

    form maps each name in EXPENSE_FIELDS to an already-stripped string.
    cleaned uses create_expense()'s keyword names: amount (float, 2 dp),
    category, expense_date ('YYYY-MM-DD') and description (str or None).
    today is injectable so tests can pin the future-date check.
    """
    amount, error = _parse_amount(form["amount"])
    if error:
        return None, error

    category = form["category"]
    if category not in CATEGORIES:
        return None, CATEGORY_ERROR

    try:
        parsed = datetime.strptime(form["date"], DATE_INPUT_FORMAT).date()
    except ValueError:
        return None, EXPENSE_DATE_ERROR
    if parsed > (today or date.today()):
        return None, FUTURE_DATE_ERROR
    if parsed < MIN_EXPENSE_DATE:
        return None, MIN_DATE_ERROR

    description = form["description"]
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return None, DESCRIPTION_LENGTH_ERROR
    if not description.isprintable():
        return None, DESCRIPTION_CHARS_ERROR

    return {
        "amount": float(amount),
        "category": category,
        "expense_date": parsed.isoformat(),
        "description": description or None,
    }, None


def _require_user(message):
    """Return (user, None) for the signed-in user, or (None, redirect to /login).

    Covers both a missing session and a stale one whose account was removed.
    """
    user_id = session.get("user_id")
    if not user_id:
        flash(message, "error")
        return None, redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if user is None:  # account removed while the session was still live
        session.clear()
        flash(message, "error")  # after clear(), or it is wiped
        return None, redirect(url_for("login"))
    return user, None


def _expense_form_context():
    """Template context shared by the add and edit expense forms."""
    return {
        "categories": CATEGORIES,
        "today": date.today().isoformat(),
        "max_description_length": MAX_DESCRIPTION_LENGTH,
    }


def _blank_expense_form(today):
    """Empty add-expense form, with the date defaulting to today."""
    return {"amount": "", "category": "", "date": today, "description": ""}


def _form_from_expense(expense):
    """Edit-form values from a stored expense row (amount as plain 2-dp text)."""
    return {
        "amount": f"{expense['amount']:.2f}",
        "category": expense["category"],
        "date": expense["date"],
        "description": expense["description"] or "",
    }


def _expense_form_from_request():
    """Return the expense form fields from the POST body, each stripped."""
    return {field: request.form.get(field, "").strip() for field in EXPENSE_FIELDS}


def _parse_date_filter(args):
    """Return (start_date, end_date, error) from the query string.

    Bounds are normalised 'YYYY-MM-DD' strings or None. On any error both
    bounds are dropped so the page falls back to all-time data.
    """
    bounds = []
    for name in ("start_date", "end_date"):
        raw = (args.get(name) or "").strip()
        if not raw:
            bounds.append(None)
            continue
        try:
            bounds.append(datetime.strptime(raw, DATE_INPUT_FORMAT).date())
        except ValueError:
            return None, None, DATE_FORMAT_ERROR

    start, end = bounds
    if start and end and start > end:
        return None, None, DATE_ORDER_ERROR
    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
        None,
    )


def _date_presets(start_date, end_date, today=None):
    """Return quick-filter presets as dicts: label, start_date, end_date, active."""
    today = today or date.today()
    presets = [
        ("This month", today.replace(day=1).isoformat(), today.isoformat()),
        (
            f"Last {LAST_N_DAYS} days",
            (today - timedelta(days=LAST_N_DAYS - 1)).isoformat(),
            today.isoformat(),
        ),
        ("All time", None, None),
    ]
    return [
        {
            "label": label,
            "start_date": preset_start,
            "end_date": preset_end,
            "active": (preset_start, preset_end) == (start_date, end_date),
        }
        for label, preset_start, preset_end in presets
    ]


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
    user, login_redirect = _require_user(PROFILE_SIGN_IN_MESSAGE)
    if login_redirect:
        return login_redirect

    start_date, end_date, filter_error = _parse_date_filter(request.args)
    bounds = {"start_date": start_date, "end_date": end_date}

    return render_template(
        "profile.html",
        user=user,
        stats=get_expense_stats(user["id"], **bounds),
        recent_transactions=get_recent_expenses(user["id"], **bounds),
        category_breakdown=get_category_breakdown(user["id"], **bounds),
        start_date=start_date,
        end_date=end_date,
        filter_error=filter_error,
        presets=_date_presets(start_date, end_date),
    )


@app.route("/analytics")
def analytics():
    _, login_redirect = _require_user(ANALYTICS_SIGN_IN_MESSAGE)
    if login_redirect:
        return login_redirect

    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    user, login_redirect = _require_user(ADD_EXPENSE_SIGN_IN_MESSAGE)
    if login_redirect:
        return login_redirect

    template_args = _expense_form_context()
    if request.method == "GET":
        form = _blank_expense_form(template_args["today"])
        return render_template("add_expense.html", form=form, **template_args)

    form = _expense_form_from_request()
    cleaned, error = _validate_expense(form)
    if error:
        return render_template(
            "add_expense.html", form=form, error=error, **template_args
        )

    # The user id comes from the session only; any form user_id is ignored.
    create_expense(
        user["id"],
        amount=cleaned["amount"],
        category=cleaned["category"],
        expense_date=cleaned["expense_date"],
        description=cleaned["description"],
    )
    flash(EXPENSE_ADDED_MESSAGE, "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    user, login_redirect = _require_user(EDIT_EXPENSE_SIGN_IN_MESSAGE)
    if login_redirect:
        return login_redirect

    # Missing and foreign ids both 404, so ids can't be probed for existence.
    expense = get_expense_by_id(id, user["id"])
    if expense is None:
        abort(404)

    template_args = {**_expense_form_context(), "expense_id": id}
    if request.method == "GET":
        form = _form_from_expense(expense)
        return render_template("edit_expense.html", form=form, **template_args)

    form = _expense_form_from_request()  # submitted values, never the stored row
    cleaned, error = _validate_expense(form)
    if error:
        return render_template(
            "edit_expense.html", form=form, error=error, **template_args
        )

    # The expense id comes from the URL and the user id from the session only.
    updated = update_expense(
        id,
        user["id"],
        amount=cleaned["amount"],
        category=cleaned["category"],
        expense_date=cleaned["expense_date"],
        description=cleaned["description"],
    )
    if not updated:  # deleted between load and save
        abort(404)
    flash(EXPENSE_UPDATED_MESSAGE, "success")
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    # The Werkzeug debugger can run arbitrary code; opt in with FLASK_DEBUG=1.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
