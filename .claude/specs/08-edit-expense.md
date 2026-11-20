# Spec: Edit Expense

## Overview
Step 7 let a signed-in user add expenses, but a typo in the amount, a wrong category or a mis-picked date can't be fixed. Step 8 adds an edit form at `/expenses/<id>/edit`. It is pre-filled with the expense's current values, validated with the same rules as the add form, and saves the changes back to the same row. On success the user gets a flash message and goes back to `/profile`, where the stats, recent transactions and category breakdown show the updated values. Each row in the profile's recent-transactions table gets an "Edit" link so the page is reachable. This is the first step where a URL contains a row id, so **ownership checks** are the main concern: a user must never be able to read or change another user's expense by guessing an id.

## Depends on
- **Step 1 (Database setup):** the `expenses` table, `CATEGORIES`, `get_db()` with `PRAGMA foreign_keys = ON`.
- **Step 3 (Login and Logout):** `session["user_id"]`.
- **Step 4 / 5 (Profile page + backend):** `/profile` as the redirect target, the recent-transactions table and `get_recent_expenses()`.
- **Step 6 (Date filter):** `DATE_INPUT_FORMAT`.
- **Step 7 (Add expense):** `_validate_expense()`, `EXPENSE_FIELDS`, the validation constants and messages, `add_expense.html` and `add_expense.css` as the form design to reuse.

## Routes
- `GET /expenses/<int:id>/edit`: renders the edit form pre-filled with the expense's current values. Logged-in only, and only for the owner.
- `POST /expenses/<int:id>/edit`: validates the form, updates the expense, flashes and redirects to `/profile`. Logged-in only, and only for the owner.

Both methods are handled by the existing `edit_expense(id)` view, now `methods=["GET", "POST"]`, replacing the stub's raw-string return. The URL rule `/expenses/<int:id>/edit` and endpoint name `edit_expense` stay the same.

**Access control** (in this order):
1. Use `_require_user(EDIT_EXPENSE_SIGN_IN_MESSAGE)` with the message "Please sign in to edit an expense.". If no session or the session is stale, redirect to `/login`. This applies to GET and POST. A signed-out POST must never update anything.
2. Load the expense with `get_expense_by_id(id, user["id"])`. If it returns `None` (no such id **or** it belongs to another user), call `abort(404)`. Use the same 404 in both cases so the response doesn't reveal whether an id exists.

**GET:** render `edit_expense.html` with `form` pre-filled from the row:
- `amount` formatted to 2 decimals as a plain string (e.g. `"450.50"`, no `₹`, no thousands separator) so it re-validates cleanly
- `category`, `date` as stored
- `description`, with `None` shown as `""`

Pass the same `categories`, `today` and `max_description_length` that `add_expense()` passes, plus `expense_id`.

**POST:** build `form` from `request.form` exactly as `add_expense()` does (strip each field in `EXPENSE_FIELDS`) and validate it with the existing `_validate_expense(form)`. Do not copy or fork the validation rules. Same messages, same field order, same limits (amount > 0, ≤ ₹10,00,000, ≤ 2 dp; category in `CATEGORIES`; real date, not in the future, not before 2000-01-01; description ≤ 200 printable chars, empty → `None`).
- **Invalid:** re-render `edit_expense.html` with status **200**, the error in a `role="alert"` element, and the *submitted* values preserved, not the stored ones. Nothing is updated.
- **Valid:** call `update_expense(id, user["id"], amount=…, category=…, expense_date=…, description=…)`. If it returns `False` (the row was deleted or changed owner between load and save), `abort(404)`. Otherwise flash "Expense updated." (category `success`) and redirect to `url_for("profile")`.

The expense id comes only from the URL, and the user id comes only from the session. Any `id`, `user_id` or `expense_id` fields in the POST body are ignored.

## Database changes
No schema changes. The `expenses` table already has every column needed.

Add two helpers to `database/db.py` and change one:

- **New:** `get_expense_by_id(expense_id, user_id)`: returns the row (`id, user_id, amount, category, date, description`) for that id **only if it belongs to `user_id`** (`WHERE id = ? AND user_id = ?`), else `None`. Closes the connection in `finally`.
- **New:** `update_expense(expense_id, user_id, amount, category, expense_date, description=None)`: a parameterised `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? WHERE id = ? AND user_id = ?` inside `with conn:`. It returns `True` if exactly one row changed (`cursor.rowcount == 1`), else `False`. It never touches `user_id` or `created_at`. Ownership is enforced in the SQL itself, not only in the route.
- **Change:** `get_recent_expenses()` also selects `id` so the profile can build per-row edit links. Ordering, limit and date-filter behaviour are unchanged.

## Templates
- **Create:**
  - `templates/edit_expense.html`: extends `base.html` and links `css/add_expense.css` (reused; no new stylesheet unless something edit-specific is needed). It uses the same card and field markup as `add_expense.html`, with these differences:
    - heading "Edit expense" and a sub-line such as "Update the details of this expense"
    - `<form method="post" action="{{ url_for('edit_expense', id=expense_id) }}" novalidate>`
    - fields: amount (₹ prefix, `type="number" step="0.01" min="0.01" inputmode="decimal"`), category `<select>` with the current category selected, date (`max="{{ today }}"`), description (`maxlength`, marked optional). Each field has a `<label for=…>`.
    - an error block with `role="alert"` when `error` is set
    - a primary "Save changes" submit button and a "Cancel" link to `url_for('profile')`
- **Modify:**
  - `templates/profile.html`: add a last column to the recent-transactions table. The header cell is visually hidden, e.g. `<th scope="col"><span class="visually-hidden">Actions</span></th>`, or the equivalent existing utility class. Each row gets an "Edit" link to `url_for('edit_expense', id=txn.id)` with an accessible name that identifies the row, e.g. `aria-label="Edit {{ txn.description or txn.category }} on {{ txn.date }}"`. Keep the date-filter query string out of the link; returning to the filtered view is out of scope.

## Files to change
- `app.py`:
  - Import `get_expense_by_id`, `update_expense` and `abort`.
  - Add the constants `EDIT_EXPENSE_SIGN_IN_MESSAGE = "Please sign in to edit an expense."` and `EXPENSE_UPDATED_MESSAGE = "Expense updated."`.
  - Replace the `edit_expense(id)` stub with the GET/POST view above. Move it out of the "Placeholder routes" section, next to `add_expense()`.
  - Optionally, extract the shared `template_args` dict (`categories`, `today`, `max_description_length`) into a small helper used by both add and edit, so it isn't duplicated.
- `database/db.py`: add `get_expense_by_id()` and `update_expense()`, and add `id` to `get_recent_expenses()`.
- `templates/profile.html`: the per-row Edit link and the actions column.
- `static/css/profile.css`: style the Edit link (small, text or ghost style, `nowrap`), using CSS variables only.
- `tests/test_expense_queries.py`: the exact-keys assertion on `get_recent_expenses()` rows (`{"date", "description", "category", "amount"}`) must now include `"id"`.
- `CLAUDE.md`:
  - Mark `GET/POST /expenses/<id>/edit` as implemented (Step 8) in the routes table.
  - Add `get_expense_by_id()` and `update_expense()` (Step 8) to the expense helpers list, and note that `get_recent_expenses()` now returns `id`.

## Files to create
- `templates/edit_expense.html`
- `tests/test_edit_expense.py`: tests for the Definition of done below.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only (`?` placeholders). Never use f-strings or `%`-formatting with values in SQL.
- Passwords are hashed with werkzeug. This step doesn't touch passwords.
- Use CSS variables and never hardcode hex values. No inline `<style>` tags.
- All templates extend `base.html`.
- Every internal link and the form `action` use `url_for()`.
- All SQL stays in `database/db.py`. `edit_expense()` must not call `get_db()`.
- **Ownership is enforced twice:** in `get_expense_by_id()` (read) and in `update_expense()`'s `WHERE id = ? AND user_id = ?` (write). Another user's expense always returns **404**, never 403, a redirect or a pre-filled form.
- Use `abort(404)` for missing or foreign expenses. Never return a raw error string.
- Reuse `_validate_expense()` and the Step 7 constants. Don't duplicate the validation rules.
- `user_id` comes only from the session, and the expense id only from the URL.
- Invalid input never causes a 500 or a 400. It re-renders the form (200) with an inline error and the submitted values.
- Use Post/Redirect/Get: a successful POST always redirects.
- Keep Jinja auto-escaping on. Never use `|safe`.
- Vanilla HTML/CSS only. The form must work with JavaScript disabled.
- Out of scope:
  - deleting expenses (Step 9). Leave the `/expenses/<id>/delete` stub unchanged.
  - an edit link anywhere other than the profile's recent-transactions table
  - preserving the profile date filter across the edit round-trip
  - change history and optimistic-locking or conflict detection
  - CSRF tokens (known gap, no new packages)
- The app stays on port 5001.

## Definition of done
- [ ] Signed-out `GET /expenses/<id>/edit` redirects to `/login` with "Please sign in to edit an expense."
- [ ] Signed-out `POST /expenses/<id>/edit` redirects to `/login` and the row is unchanged.
- [ ] A session whose user no longer exists is cleared and redirected to `/login`.
- [ ] Signed-in `GET` for the user's own expense returns 200, with every field pre-filled with the stored values (amount as `"450.50"`-style, the correct category selected, the stored date, the description or empty).
- [ ] `GET` for a non-existent id returns 404.
- [ ] `GET` for **another user's** expense returns 404 and the page doesn't contain that expense's description or amount.
- [ ] `POST` to another user's expense returns 404 and their row is unchanged in the DB.
- [ ] A valid POST updates exactly that row (amount, category, date, description), leaves `user_id` and `created_at` unchanged, doesn't change the row count, redirects to `/profile`, and shows "Expense updated."
- [ ] After editing, `/profile` shows the new values in recent transactions, and the total and category breakdown reflect the change.
- [ ] Clearing the description stores `NULL`.
- [ ] Each invalid case returns 200 with the same error message as `/expenses/add`, shows the submitted (not stored) values, and leaves the row unchanged: missing amount, `0`, `-5`, `abc`, `nan`, `12.345`, more than 1,000,000, unknown category, missing date, `2026-02-30`, a future date, a description over 200 characters.
- [ ] `user_id` and `id` fields in the POST body are ignored. The row keeps its owner and the URL's id is the one updated.
- [ ] A `<script>` description is stored as-is and rendered escaped on `/profile` and in the edit form.
- [ ] `get_expense_by_id()` returns `None` for the wrong user. `update_expense()` returns `False` and changes nothing for the wrong user or a missing id, and returns `True` on success.
- [ ] `get_recent_expenses()` rows include `id`. Every row in the profile's recent-transactions table has an "Edit" link to `/expenses/<that id>/edit`.
- [ ] The edit page is usable at mobile width (fields stack, no horizontal page scroll), and the profile table with the new column still scrolls inside `.table-scroll`, not the page.
- [ ] The delete stub is unchanged.
- [ ] `pytest` passes in full, including the updated `test_expense_queries.py` and all earlier tests.
- [ ] CLAUDE.md marks `/expenses/<id>/edit` as implemented and documents the new helpers.
