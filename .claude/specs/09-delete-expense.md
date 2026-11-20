# Spec: Delete Expense

## Overview
Steps 7 and 8 let a signed-in user add and edit expenses, but there's no way to remove one that was added by mistake or twice. Step 9 replaces the last stub, `/expenses/<id>/delete`, with a two-step delete flow. `GET /expenses/<id>/delete` shows a confirmation page with the expense's details, a "Delete expense" button and a "Cancel" link. `POST /expenses/<id>/delete` permanently removes the row, flashes "Expense deleted." and redirects to `/profile`, where the stats, recent transactions and category breakdown no longer include it. Each row in the profile's recent-transactions table gets a "Delete" link next to "Edit" that leads to the confirmation page. The two-step flow has two jobs. It keeps the state change on **POST** so it stays covered by the `SameSite=Lax` CSRF mitigation; CLAUDE.md requires this. It also works with JavaScript disabled, because it doesn't rely on a JS `confirm()`. As in Step 8, **ownership** is the main concern: a user must never be able to see or delete another user's expense by guessing an id.

## Depends on
- **Step 1 (Database setup):** the `expenses` table, `get_db()` with `PRAGMA foreign_keys = ON`.
- **Step 3 (Login and Logout):** `session["user_id"]`.
- **Step 4 / 5 (Profile page + backend):** `/profile` as the redirect target, the recent-transactions table, the stats and the category breakdown.
- **Step 7 (Add expense):** the `inr` and `short_date` template filters, and `add_expense.css` (card and button styling to reuse).
- **Step 8 (Edit expense):** `get_expense_by_id()`, the `_require_user()` + `abort(404)` ownership pattern, `id` on `get_recent_expenses()` rows, and the profile's actions column.

## Routes
- `GET /expenses/<int:id>/delete`: renders the confirmation page for the expense. Logged-in only, and only for the owner.
- `POST /expenses/<int:id>/delete`: deletes the expense, flashes and redirects to `/profile`. Logged-in only, and only for the owner.

Both methods are handled by the existing `delete_expense(id)` view, now `methods=["GET", "POST"]`, replacing the stub's raw-string return. The URL rule `/expenses/<int:id>/delete` and endpoint name `delete_expense` stay the same.

**Access control** (in this order, for both methods):
1. Use `_require_user(DELETE_EXPENSE_SIGN_IN_MESSAGE)` with the message "Please sign in to delete an expense.". If there's no session or the session is stale, redirect to `/login`. A signed-out POST must never delete anything.
2. Load the expense with `get_expense_by_id(id, user["id"])`. If it returns `None` (no such id **or** it belongs to another user), call `abort(404)`. Use the same 404 in both cases.

**GET:** render `delete_expense.html` with the `expense` row. The GET does not change anything.

**POST:** call `delete_expense(id, user["id"])` (the DB helper; see the naming note under Files to change). If it returns `False` (already deleted, e.g. a double-submit or a second tab), `abort(404)`. Otherwise flash "Expense deleted." (category `success`) and redirect to `url_for("profile")`.

The expense id comes only from the URL, and the user id comes only from the session. Any `id`, `user_id` or `expense_id` fields in the POST body are ignored. The POST needs no form fields.

## Database changes
No schema changes. Nothing references `expenses.id`, so a plain row delete is safe and needs no cascade.

Add one helper to `database/db.py`:

- **New:** `delete_expense(expense_id, user_id)`: runs a parameterised `DELETE FROM expenses WHERE id = ? AND user_id = ?` inside `with conn:` and closes the connection in `finally`. It returns `True` if exactly one row was deleted (`cursor.rowcount == 1`), else `False`. Ownership is enforced in the SQL itself, not only in the route.

## Templates
- **Create:**
  - `templates/delete_expense.html`: extends `base.html`, links `css/add_expense.css` (reused), and uses the same `auth-section` / `auth-container` / `auth-card expense-card` shell as `edit_expense.html`.
    - heading "Delete expense" and a sub-line such as "This can't be undone."
    - a summary of the expense: amount (`|inr`), category, date (`|short_date`) and description (or a muted "No description"). Use a `<dl>` or equivalent semantic markup. All values are auto-escaped.
    - `<form method="post" action="{{ url_for('delete_expense', id=expense.id) }}">` containing only a submit button "Delete expense" in a danger style
    - a "Cancel" link to `url_for('profile')`
- **Modify:**
  - `templates/profile.html`: in the existing actions cell of each recent-transactions row, add a "Delete" link to `url_for('delete_expense', id=txn.id)` next to the Edit link. Give it an accessible name that identifies the row, e.g. `aria-label="Delete {{ txn.description or txn.category }} on {{ txn.date }}"`. The link is a GET to the confirmation page, so it changes nothing by itself.

## Files to change
- `app.py`:
  - Import the DB helper under a different name so it doesn't clash with the view function `delete_expense`, e.g. `from database.db import delete_expense as db_delete_expense`. Alternatively, name the helper `delete_expense_by_id`. Either is fine; the endpoint name must stay `delete_expense`.
  - Add the constants `DELETE_EXPENSE_SIGN_IN_MESSAGE = "Please sign in to delete an expense."` and `EXPENSE_DELETED_MESSAGE = "Expense deleted."`.
  - Replace the `delete_expense(id)` stub with the GET/POST view above. Move it next to `edit_expense()` and remove the now-empty "Placeholder routes" section header.
- `database/db.py`: add `delete_expense()`.
- `templates/profile.html`: the per-row Delete link.
- `static/css/profile.css`: style the Delete link to match `.txn-edit-link`, with a danger color (`var(--danger)`), and space it from Edit. Check that the table's `min-width` still fits both links. CSS variables only.
- `static/css/add_expense.css`: a danger button variant (e.g. `.btn-danger` using `var(--danger)` / `var(--danger-light)`) and the summary list styles, if `style.css` doesn't already provide them. CSS variables only.
- `CLAUDE.md`:
  - Mark `GET/POST /expenses/<id>/delete` as implemented (Step 9) in the routes table.
  - Add `delete_expense()` (Step 9) to the expense helpers list.
  - Update the "Do not implement a stub route" and "State-changing routes must be POST" notes, since no stubs remain.

## Files to create
- `templates/delete_expense.html`
- `tests/test_delete_expense.py`: tests for the Definition of done below. Use the shared helpers in `tests/helpers.py` (`login`, `register_and_login`, `user_id_for`, `expense_rows`, `expense_count`, `page_text`, …).

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only (`?` placeholders). Never use f-strings or `%`-formatting with values in SQL.
- Passwords are hashed with werkzeug. This step doesn't touch passwords.
- Use CSS variables and never hardcode hex values. No inline `<style>` tags.
- All templates extend `base.html`.
- Every internal link and the form `action` use `url_for()`.
- All SQL stays in `database/db.py`. The `delete_expense` view must not call `get_db()`.
- **Deletion happens only on POST.** GET only renders the confirmation page and never changes the DB.
- **Ownership is enforced twice:** in `get_expense_by_id()` (before the page or the delete) and in `delete_expense()`'s `WHERE id = ? AND user_id = ?`. Another user's expense always returns **404**, never 403, a redirect or a confirmation page with their data.
- Use `abort(404)` for missing or foreign expenses. Never return a raw error string.
- `user_id` comes only from the session, and the expense id only from the URL.
- Use Post/Redirect/Get: a successful POST always redirects.
- Keep Jinja auto-escaping on. Never use `|safe`.
- Vanilla HTML/CSS only. The flow must work with JavaScript disabled. Don't use a JS `confirm()` as the only safeguard.
- Out of scope:
  - soft delete, undo or a trash view
  - bulk delete
  - a delete button on the edit page or anywhere other than the profile's recent-transactions table
  - preserving the profile date filter across the delete round-trip
  - CSRF tokens (known gap, no new packages)
- The app stays on port 5001.

## Definition of done
- [ ] Signed-out `GET /expenses/<id>/delete` redirects to `/login` with "Please sign in to delete an expense."
- [ ] Signed-out `POST /expenses/<id>/delete` redirects to `/login` and the row still exists.
- [ ] A session whose user no longer exists is cleared and redirected to `/login`, for both methods.
- [ ] Signed-in `GET` for the user's own expense returns 200, shows its amount, category, date and description, has a POST form to `/expenses/<id>/delete` and a Cancel link to `/profile`, and doesn't delete anything.
- [ ] `GET` and `POST` for a non-existent id return 404.
- [ ] `GET` for **another user's** expense returns 404 and the page doesn't contain that expense's description or amount.
- [ ] `POST` to another user's expense returns 404 and their row still exists.
- [ ] A valid POST deletes exactly that row, decreases the expense count by one, leaves the user's other expenses and other users' expenses untouched, redirects to `/profile`, and shows "Expense deleted."
- [ ] After deleting, `/profile` no longer lists the expense, and the total, transaction count and category breakdown reflect the removal.
- [ ] Deleting the user's only expense leaves `/profile` showing the "No transactions yet" empty state without errors.
- [ ] A second POST to the same id (double-submit) returns 404 and changes nothing else.
- [ ] `user_id`, `id` and `expense_id` fields in the POST body are ignored. Only the URL's id, for the session's user, is deleted.
- [ ] A `<script>` description is rendered escaped on the confirmation page.
- [ ] `delete_expense()` returns `True` on success, and returns `False` and deletes nothing for the wrong user or a missing id.
- [ ] Every row in the profile's recent-transactions table has a "Delete" link to `/expenses/<that id>/delete` with a row-specific `aria-label`, next to the existing Edit link.
- [ ] The confirmation page is usable at mobile width with no horizontal page scroll, and the profile table still scrolls inside `.table-scroll`, not the page.
- [ ] No raw-string stub routes remain in `app.py`.
- [ ] `pytest` passes in full, including all earlier tests.
- [ ] CLAUDE.md marks `/expenses/<id>/delete` as implemented and documents `delete_expense()`.
