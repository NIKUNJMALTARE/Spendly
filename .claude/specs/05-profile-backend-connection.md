# Spec: Profile Backend Connection

## Overview
Step 4 built the profile page's design, but its summary stats, recent-transactions table and category breakdown come from hard-coded constants in `app.py` (`PROFILE_STATS`, `PROFILE_RECENT_TRANSACTIONS`, `PROFILE_CATEGORY_BREAKDOWN`). Every user sees the same made-up ₹12,000. Step 5 connects those three sections to the `expenses` table, so the page shows the signed-in user's own spending. It also adds the app's first expense read helpers to `database/db.py`. Steps 7–9 (add, edit and delete expenses) will reuse them. Finally, the demo seed data is corrected so the demo account looks sensible in rupees: today the amounts are dollar-sized and some dates fall in the future.

## Depends on
- **Step 1 (Database setup):** the `expenses` table, `CATEGORIES`, `get_db()` and `seed_db()`.
- **Step 3 (Login and Logout):** `session["user_id"]`.
- **Step 4 (Profile Page Design):** `/profile`, `profile.html`, `profile.css`, the `inr` filter and the empty-state markup.

## Routes
No new routes.

`GET /profile` (changed). Access control and the missing-user handling stay exactly as in Step 4. After loading the user, the route calls the three new helpers with `user["id"]` and passes the results to the template under the same names it uses today: `stats`, `recent_transactions`, `category_breakdown`. The route stays "fetch, then render", and all computation lives in `database/db.py`.

## Database changes
No schema changes. The `users` and `expenses` tables stay as they are.

Add three read-only helpers to `database/db.py`. Each one opens a connection with `get_db()`, uses `?` placeholders, closes the connection in `finally`, and filters by `user_id`, so a user never sees another user's expenses.

- `get_expense_stats(user_id)` returns a dict:
  - `total_spent`: float, the sum of `amount`; `0.0` when the user has no expenses
  - `transaction_count`: int, the number of expense rows
  - `top_category`: the category with the highest total, ties broken alphabetically; `None` when the user has no expenses
- `get_recent_expenses(user_id, limit=5)` returns a list of dicts with keys `date`, `description`, `category`, `amount`, ordered by `date DESC, id DESC` and limited to `limit` rows. A `NULL` description comes back as `""`.
- `get_category_breakdown(user_id)` returns a list of dicts with keys `name`, `amount`, `percent`:
  - one entry per category that has spending, ordered by `amount DESC, name ASC`
  - `percent` is a whole number of the user's total; the percentages add up to exactly 100, using the largest-remainder method
  - an empty list when the user has no expenses

Seed data fixes in `seed_db()` (only new or empty databases are affected, because seeding runs only when `users` is empty):
- Rescale `SAMPLE_EXPENSES` to realistic rupee amounts (e.g. lunch ≈ ₹250, metro pass ≈ ₹600, electricity ≈ ₹1,800), keeping the same 8 categories and descriptions.
- Seeded dates must never be in the future. Use day offsets back from today (`today - timedelta(days=n)`) instead of `today.replace(day=d)`.

## Templates
- **Create:** none.
- **Modify:**
  - `templates/profile.html`:
    - Rename the overview heading from "This month" to "Overview", because the stats now cover all of the user's expenses, not just the current month.
    - Show `—` for Top category when `stats.top_category` is `None`.
    - Show `—` in the Description cell when it is empty.
    - Everything else (markup, classes, empty states, bar widths) stays unchanged.

## Files to change
- `app.py`:
  - Delete the `PROFILE_CATEGORY_BREAKDOWN`, `PROFILE_RECENT_TRANSACTIONS` and `PROFILE_STATS` constants and their comment.
  - Import the three new helpers, and call them in `profile()`.
- `database/db.py`: add the three helpers, rescale `SAMPLE_EXPENSES`, and change seeded dates to past day offsets (import `timedelta`).
- `templates/profile.html`: the changes listed under Templates.
- `tests/test_profile.py`:
  - Remove or rewrite the tests that read the placeholder constants (`test_placeholder_data_consistent`, `test_category_bars_match_percent`, `test_empty_transactions_state` and any others that use `PROFILE_*`).
  - Add tests for the Definition of done below.
- `CLAUDE.md`:
  - Update the `GET /profile` row to "Implemented (Step 4 design, Step 5 real data)".
  - Add the three expense helpers to the `database/db.py` note.

## Files to create
None. New tests go in the existing `tests/test_profile.py`. A separate `tests/test_expense_queries.py` is acceptable if the helper tests grow large.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Use parameterised queries only (`?` placeholders), never f-strings in SQL. `limit` must also be passed as a parameter.
- Passwords are hashed with werkzeug. This step doesn't touch passwords.
- Use CSS variables and never hardcode hex values. This step should need no CSS changes.
- All templates extend `base.html`.
- All SQL and all aggregation or percentage math go in `database/db.py`. `profile()` must not call `get_db()` or compute totals itself.
- Every expense query must filter by the signed-in user's id.
- Prefer SQL aggregation (`SUM`, `COUNT`, `GROUP BY`) over loading every row into Python. The largest-remainder percent rounding may be done in Python on the grouped rows.
- Keep the `inr` and `month_year` filters, and keep auto-escaping on. Never use `|safe` on descriptions, which are user data.
- Out of scope:
  - date filters or a month-only view
  - charts beyond the existing bars
  - pagination or a full expense list page
  - add, edit or delete expenses (Steps 7–9)
  - a `login_required` decorator
- Don't implement the `/expenses/*` stubs.
- The app stays on port 5001.

## Definition of done
- [ ] Signed in as the demo user on a freshly seeded database, `/profile` shows a total, a count (8) and a top category that match the seeded expenses, not the old ₹12,000 / 18 placeholder values.
- [ ] The recent-transactions table shows the demo user's 5 most recent expenses, newest first.
- [ ] The category breakdown lists only the categories the user has spent in, ordered by amount (highest first). The bar widths add up to exactly 100%, and each width matches its percent.
- [ ] A newly registered user with no expenses sees ₹0.00 total, 0 transactions, `—` for top category, "No transactions yet." and "No spending yet.", without errors.
- [ ] Expenses inserted for user B never appear on user A's profile: stats, table and breakdown are all isolated.
- [ ] An expense with a `NULL` description renders `—` in the table, with no "None".
- [ ] A description containing HTML (e.g. `<b>x</b>`) is rendered escaped.
- [ ] `get_expense_stats`, `get_recent_expenses` and `get_category_breakdown` each return the documented shape for a user with expenses and for a user with none. `get_recent_expenses` respects `limit`.
- [ ] Percent rounding gives a sum of exactly 100 for awkward splits (e.g. three equal categories → 34/33/33).
- [ ] Top-category ties are broken alphabetically.
- [ ] A freshly seeded database has no expense dated after today, and the demo amounts are in the hundreds or thousands of rupees.
- [ ] `app.py` no longer contains `PROFILE_STATS`, `PROFILE_RECENT_TRANSACTIONS` or `PROFILE_CATEGORY_BREAKDOWN`.
- [ ] The overview heading reads "Overview".
- [ ] All Step 4 behaviour still works: signed-out redirect, missing-user handling, avatar initials, nav link and responsive layout.
- [ ] `pytest` passes in full.
- [ ] CLAUDE.md shows `/profile` as connected to real data in Step 5 and lists the new helpers.
