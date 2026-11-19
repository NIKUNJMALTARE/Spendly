# Spec: Add Expense

## Overview
Until now the only expenses in Spendly are the seeded demo rows and whatever tests insert directly. Step 7 lets a signed-in user record their own expense through a form at `/expenses/add`: amount, category, date and an optional description. On success the expense is saved against the user's account, a success message is flashed, and the user is sent to `/profile`, where the new row immediately shows up in the stats, recent transactions and category breakdown built in Steps 5–6. This replaces the Step 7 raw-string stub with a real page, and it is the first step that writes expense data. Edit (Step 8) and delete (Step 9) build on it.

## Depends on
- **Step 1 (Database setup):** the `expenses` table, the `CATEGORIES` list, `get_db()` with `PRAGMA foreign_keys = ON`.
- **Step 3 (Login and Logout):** `session["user_id"]`.
- **Step 4 (Profile Page Design):** `/profile` as the redirect target and the `profile.html` layout, which gets the "Add expense" entry point.
- **Step 5 (Profile Backend Connection):** the expense helpers that will show the new row.
- **Step 6 (Date Filter):** `DATE_INPUT_FORMAT` and the strict `YYYY-MM-DD` parsing approach, which the date field reuses.

## Routes
- `GET /expenses/add`: renders the add-expense form; logged-in only.
- `POST /expenses/add`: validates the form, inserts the expense, flashes and redirects to `/profile`; logged-in only.

Both methods are handled by the existing `add_expense()` view (`methods=["GET", "POST"]`), replacing the stub's raw-string return.

**Access control** (same pattern as `/profile` and `/analytics`):
- No `session["user_id"]` → flash "Please sign in to add an expense." (category `error`) and redirect to `/login`. This applies to GET and POST; a signed-out POST must never insert anything.
- `user_id` in session but `get_user_by_id()` returns `None` (account removed) → `session.clear()`, then flash the same message, then redirect to `/login`.

**GET:** render `add_expense.html` with the category list and the date field pre-filled with today's date (`date.today().isoformat()`).

**POST:** read `amount`, `category`, `date`, `description` from `request.form`, strip whitespace, validate with a helper in `app.py` (e.g. `_validate_expense(amount, category, expense_date, description)` returning `(cleaned_values, error)`, in the style of `_validate_registration()`), checking the first invalid field in this order:

| Field | Rule | Error message |
|---|---|---|
| `amount` | Required; parses as a finite number (reject `nan`, `inf`); `> 0`; at most `1,000,000`; at most 2 decimal places | "Please enter an amount greater than zero." / "Amount must be at most ₹10,00,000." / "Amount can have at most 2 decimal places." |
| `category` | Must be exactly one of `CATEGORIES` from `database/db.py` | "Please choose a valid category." |
| `date` | Required; a real calendar date in `YYYY-MM-DD` (parsed with `DATE_INPUT_FORMAT`); not in the future | "Please enter a valid date (YYYY-MM-DD)." / "Date can't be in the future." |
| `description` | Optional; at most 200 characters after stripping; empty becomes `None` | "Description must be at most 200 characters." |

- **Invalid:** re-render `add_expense.html` with status **200**, the error in an element with `role="alert"`, and every submitted value preserved in the form (the selected category stays selected). Nothing is inserted.
- **Valid:** call `create_expense(user_id, amount, category, expense_date, description)`, flash "Expense added." (category `success`), and redirect to `url_for("profile")`. The user id always comes from the session, never from the form.

Store the amount as a float rounded to 2 decimals and the date as the normalised `YYYY-MM-DD` string, never the raw form value.

## Database changes
No schema changes. The `expenses` table already has every column needed (`user_id`, `amount`, `category`, `date`, `description`, `created_at`).

Add one helper to `database/db.py`:

- `create_expense(user_id, amount, category, expense_date, description=None)`: inserts one row with a parameterised `INSERT`, inside `with conn:` so it commits, closes the connection in `finally`, and returns the new row id (`cursor.lastrowid`). Same shape as `create_user()`.

The `REFERENCES users(id)` constraint is enforced because `get_db()` turns foreign keys on, so inserting for a non-existent user raises `sqlite3.IntegrityError`. The route never hits this in normal use because it checks the user first.

## Templates
- **Create:**
  - `templates/add_expense.html`: extends `base.html`. A single card with:
    - heading "Add expense" and a short sub-line
    - `<form method="post" action="{{ url_for('add_expense') }}" novalidate>` (server-side validation is the source of truth)
    - **Amount:** `<input type="number" name="amount" step="0.01" min="0.01" inputmode="decimal">` with a "₹" prefix label
    - **Category:** `<select name="category">` built by looping over the categories passed from the route, with a disabled "Choose a category" placeholder selected when nothing has been chosen yet
    - **Date:** `<input type="date" name="date" max="{{ today }}">`
    - **Description:** `<input type="text" name="description" maxlength="200">`, marked optional
    - every input has a `<label for=…>`
    - an error block with `role="alert"` when `error` is set
    - a primary "Add expense" submit button and a "Cancel" link to `url_for('profile')`
- **Modify:**
  - `templates/profile.html`: add an "Add expense" button-style link (`url_for('add_expense')`) near the Overview heading / filter bar, and add a link to `url_for('add_expense')` in the "No transactions yet." empty state.

## Files to change
- `app.py`:
  - Import `create_expense` and `CATEGORIES` from `database.db`.
  - Add the message constants (`ADD_EXPENSE_SIGN_IN_MESSAGE`, error strings, `MAX_EXPENSE_AMOUNT`, `MAX_DESCRIPTION_LENGTH`) beside the existing ones.
  - Add `_validate_expense()`.
  - Replace the `add_expense()` stub with the GET/POST view described above.
- `database/db.py`: add `create_expense()`.
- `templates/profile.html`: the "Add expense" entry points.
- `static/css/profile.css`: style for the new "Add expense" link on the profile page.
- `CLAUDE.md`:
  - Mark `GET/POST /expenses/add` as implemented (Step 7) in the routes table.
  - Add `create_expense()` to the expense helpers list.
  - Add `static/css/add_expense.css` to the architecture tree.

## Files to create
- `templates/add_expense.html`
- `static/css/add_expense.css`: page-specific styles (card, ₹-prefixed amount field, select styling, button row). Reuse `.form-group`, `.form-input`, `.btn-submit` from `style.css` where they fit, and stack at mobile width.
- `tests/test_add_expense.py`: tests for the Definition of done below.

## New dependencies
No new dependencies. Use the standard library (`datetime`, `decimal` or `math`) for parsing and validation.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only (`?` placeholders), never f-strings or `%`-formatting with values in SQL.
- Passwords are hashed with werkzeug. This step doesn't touch passwords.
- Use CSS variables and never hardcode hex values. Put new styles in `add_expense.css` / `profile.css`, not inline `<style>` tags.
- All templates extend `base.html`.
- Every internal link and the form `action` use `url_for()`.
- All SQL stays in `database/db.py`. `add_expense()` must not call `get_db()`.
- The route stays "read input → validate → write → redirect / render". Validation logic lives in `_validate_expense()`, not inline in the view.
- `user_id` comes only from `session`; any `user_id` field in the form is ignored.
- Category is validated against the server-side `CATEGORIES` list. The `<select>` is not trusted.
- Invalid input never causes a 500 or a 400. It re-renders the form with an inline error.
- Use Post/Redirect/Get: a successful POST always redirects, so refreshing `/profile` never re-submits.
- Keep Jinja auto-escaping on. Never use `|safe`. A description like `<script>` must render as text on `/profile`.
- Vanilla HTML/CSS only. The form must work with JavaScript disabled.
- Out of scope:
  - editing or deleting expenses (Steps 8–9); don't implement those stubs
  - custom or user-defined categories
  - receipts or attachments, recurring expenses, multiple currencies
  - CSRF tokens (no new packages; note it as a known gap)
  - a `login_required` decorator
- The app stays on port 5001.

## Definition of done
- [ ] Signed-out `GET /expenses/add` redirects to `/login` with "Please sign in to add an expense."
- [ ] Signed-out `POST /expenses/add` redirects to `/login` and inserts no row.
- [ ] A session whose user no longer exists is cleared and redirected to `/login`.
- [ ] Signed-in `GET /expenses/add` returns 200 with labelled amount, category, date and description fields, all seven categories in the select, and the date pre-filled with today.
- [ ] A valid POST (e.g. `450.50`, `Food`, today, "Dinner") inserts exactly one row for the signed-in user, redirects to `/profile`, and shows "Expense added."
- [ ] After adding, `/profile` shows the new expense in recent transactions, the total and transaction count increase accordingly, and the category breakdown includes it.
- [ ] An empty description is stored as `NULL` and the row still appears on `/profile`.
- [ ] Each invalid case returns 200 with the matching error, preserves the submitted values, and inserts nothing: missing amount, `0`, `-5`, `abc`, `nan`, `inf`, `12.345`, more than 1,000,000, unknown category (e.g. `Crypto`), missing date, `2026-02-30`, a future date, and a description over 200 characters.
- [ ] A `user_id` field added to the POST body is ignored; the row belongs to the session user.
- [ ] A description containing `<script>alert(1)</script>` is stored as-is and rendered escaped on `/profile`.
- [ ] A SQL-injection-style description (e.g. `'); DROP TABLE expenses;--`) is stored literally and the `expenses` table is intact.
- [ ] `create_expense()` returns the new id, and calling it for a non-existent user raises `sqlite3.IntegrityError`.
- [ ] `/profile` has an "Add expense" link to `/expenses/add`, and the empty state links there too.
- [ ] The add-expense page is usable at mobile width (fields stack, no horizontal page scroll).
- [ ] The edit and delete stubs are unchanged.
- [ ] `pytest` passes in full, including all earlier tests.
- [ ] CLAUDE.md marks `/expenses/add` as implemented and documents `create_expense()`.
