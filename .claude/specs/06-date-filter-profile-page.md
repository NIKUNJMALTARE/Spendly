# Spec: Date Filter for Profile Page

## Overview
Step 5 connected the profile page to the `expenses` table, but every section covers all of the user's expenses, for all time. Step 6 adds a date filter to `/profile` so the user can narrow the overview stats, the recent-transactions table and the category breakdown to a date range: a custom "from / to" range, or one of a few quick presets (This month, Last 30 days, All time). The filter is carried in the query string (`/profile?start_date=…&end_date=…`), so a filtered view can be bookmarked or refreshed, and it needs no JavaScript. The three Step 5 expense helpers gain optional date bounds, which Steps 7–9 and any later reports can reuse.

## Depends on
- **Step 1 (Database setup):** the `expenses` table, whose `date` column stores ISO `YYYY-MM-DD` text.
- **Step 3 (Login and Logout):** `session["user_id"]`.
- **Step 4 (Profile Page Design):** `/profile`, `profile.html`, `profile.css`, and the empty-state markup.
- **Step 5 (Profile Backend Connection):** `get_expense_stats()`, `get_recent_expenses()` and `get_category_breakdown()`.

## Routes
No new routes.

`GET /profile` (changed). Access control and the missing-user handling stay exactly as in Steps 4–5. The route now also reads two optional query parameters:

- `start_date`: inclusive lower bound, `YYYY-MM-DD`
- `end_date`: inclusive upper bound, `YYYY-MM-DD`

Behaviour:
- Neither parameter given (or both empty) → no filter, the same output as Step 5 ("All time").
- Only one given → an open-ended range (e.g. only `start_date` means "from that date onwards").
- A value that is not a real calendar date in `YYYY-MM-DD` form (e.g. `2026-02-30`, `abc`, `19/11/2026`) → the filter is ignored, the page shows all-time data, and an inline error message is shown above the overview: "Please enter valid dates (YYYY-MM-DD)." The status is still 200.
- `start_date` later than `end_date` → the filter is ignored, all-time data is shown, and an inline error message is shown: "Start date must be on or before end date." The status is still 200.
- Whitespace around values is stripped. Unknown query parameters are ignored.

Parsing and validation go in a small helper in `app.py` (e.g. `_parse_date_filter(args)` returning `(start_date, end_date, error)`), in the same style as `_validate_registration()` / `_validate_login()`. The route stays "read input, fetch, render": it passes the validated bounds to the three helpers and renders the template.

The route passes these extra values to the template:
- `start_date`, `end_date`: the applied bounds as `YYYY-MM-DD` strings, or `None`
- `filter_error`: the error message, or `None`
- `presets`: a list of quick-filter presets, each with a `label`, `start_date`, `end_date` and an `active` flag, computed from today's date:
  - **This month**: the 1st of the current month → today
  - **Last 30 days**: today − 29 days → today (30 days including today)
  - **All time**: no bounds
  
  A preset is `active` when the applied bounds exactly equal its bounds ("All time" is active when no filter is applied). Preset date computation may live in `app.py` as a helper; it is not database logic.

## Database changes
No schema changes. The `users` and `expenses` tables stay as they are.

Extend the three Step 5 helpers in `database/db.py` with optional keyword arguments `start_date=None` and `end_date=None` (ISO `YYYY-MM-DD` strings):

- `get_expense_stats(user_id, start_date=None, end_date=None)`
- `get_recent_expenses(user_id, limit=5, start_date=None, end_date=None)`
- `get_category_breakdown(user_id, start_date=None, end_date=None)`

Rules:
- When a bound is `None`, that side of the range is open. With both `None`, results are identical to Step 5, so existing callers and tests keep working unchanged.
- Bounds are inclusive: `date >= start_date` and `date <= end_date`. Because `date` is ISO text, string comparison is correct.
- Every query still filters by `user_id`.
- The return shapes are exactly as documented in Step 5. An empty range gives `total_spent` 0.0, `transaction_count` 0, `top_category` `None`, and empty lists.
- Build the shared `WHERE` clause in one private helper (e.g. `_date_range_clause(user_id, start_date, end_date)` returning a SQL fragment and a params tuple). Only fixed SQL fragments (`"AND date >= ?"`) may be concatenated; every value must go through a `?` placeholder.

## Templates
- **Create:** none.
- **Modify:**
  - `templates/profile.html`:
    - Add a filter bar between the profile card and the overview section:
      - a `<form method="get" action="{{ url_for('profile') }}">` with two labelled `<input type="date">` fields named `start_date` and `end_date`, pre-filled with the applied bounds, and an "Apply" submit button
      - a "Clear" link to `url_for('profile')` (no query string)
      - a row of preset links built with `url_for('profile', start_date=…, end_date=…)`; the active preset gets an `is-active` class and `aria-current="true"`
    - When `filter_error` is set, show it in an element with `role="alert"` near the filter bar.
    - Under the "Overview" heading, show the applied range in a short caption: "All time", "1 Nov 2026 – 19 Nov 2026", "From 1 Nov 2026" or "Until 19 Nov 2026".
    - When a filter is applied and has no matching expenses, the empty states read "No transactions in this period." and "No spending in this period." Without a filter they keep the Step 5 wording ("No transactions yet." / "No spending yet.").
    - Everything else (stats cards, table, bars, auto-escaping) stays unchanged.

## Files to change
- `app.py`:
  - Add `_parse_date_filter()` and the preset helper.
  - Update `profile()` to pass the bounds to the helpers and the new values to the template.
  - Add a template filter for the human-readable caption date (e.g. `short_date`: `'2026-11-01'` → `'1 Nov 2026'`), next to `month_year`.
- `database/db.py`: add `_date_range_clause()` and the optional bounds to the three helpers.
- `templates/profile.html`: the changes listed under Templates.
- `static/css/profile.css`: styles for the filter bar, preset links (including `.is-active`), the caption and the error message, using existing CSS variables only. Must stack cleanly on narrow screens.
- `tests/test_profile.py` and/or `tests/test_expense_queries.py`: add tests for the Definition of done below.
- `CLAUDE.md`:
  - Update the `GET /profile` row to mention the Step 6 date filter (`?start_date=&end_date=`).
  - Note the optional `start_date` / `end_date` arguments on the three expense helpers.

## Files to create
None.

## New dependencies
No new dependencies. Use the standard library `datetime` for parsing and preset dates.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Use parameterised queries only (`?` placeholders), never f-strings or `%`-formatting with values in SQL. Date bounds must be passed as parameters.
- Passwords are hashed with werkzeug. This step doesn't touch passwords.
- Use CSS variables and never hardcode hex values. Put new styles in `profile.css`, not inline `<style>` tags.
- All templates extend `base.html`.
- Every internal link and the form `action` use `url_for()`.
- Validate dates with `datetime.strptime(value, "%Y-%m-%d")` (or `date.fromisoformat`) and pass the normalised `YYYY-MM-DD` string to the DB, never the raw query value.
- Invalid input must never cause a 500 or a 400. Fall back to all-time data and show the inline error.
- All SQL and aggregation stay in `database/db.py`. `profile()` must not call `get_db()`.
- Vanilla HTML only. The filter must work with JavaScript disabled; no JS is required for this step.
- Keep auto-escaping on. Never use `|safe`. Query-string values echoed back into inputs must be escaped (Jinja's default).
- Out of scope:
  - filtering by category, amount or description search
  - pagination or a "show all transactions" page
  - persisting the filter in the session or the database
  - charts beyond the existing bars
  - add, edit or delete expenses (Steps 7–9); don't implement the `/expenses/*` stubs
  - a `login_required` decorator
- The app stays on port 5001.

## Definition of done
- [ ] `/profile` with no query string shows exactly the Step 5 all-time data, the caption reads "All time", and the "All time" preset is marked active.
- [ ] `/profile?start_date=X&end_date=Y` shows only expenses dated between X and Y inclusive in the stats, the recent-transactions table and the category breakdown. An expense dated exactly X or exactly Y is included.
- [ ] Only `start_date` gives an open-ended "from" range; only `end_date` gives an open-ended "until" range; the caption reflects each case.
- [ ] Submitting the form with two dates lands on `/profile?start_date=…&end_date=…` and the date inputs stay pre-filled with the applied values.
- [ ] "This month" covers the 1st of the current month through today; "Last 30 days" covers today − 29 days through today. The matching preset is marked active (`is-active`, `aria-current`) when its range is applied.
- [ ] "Clear" returns to `/profile` with no filter.
- [ ] An invalid date (`2026-02-30`, `abc`) returns 200 with all-time data and "Please enter valid dates (YYYY-MM-DD)."
- [ ] `start_date` after `end_date` returns 200 with all-time data and "Start date must be on or before end date."
- [ ] A range with no expenses shows ₹0.00, 0 transactions, `—` for top category, "No transactions in this period." and "No spending in this period."
- [ ] A filtered category breakdown still sums to exactly 100% and is computed only from the expenses in the range.
- [ ] A filtered view never shows another user's expenses.
- [ ] A SQL-injection-style value (e.g. `start_date=2026-01-01' OR '1'='1`) is treated as invalid and changes nothing.
- [ ] The three helpers called without date arguments return exactly what they returned in Step 5. All Step 5 tests still pass unchanged.
- [ ] Signed-out users requesting `/profile?start_date=…` are still redirected to `/login`.
- [ ] The filter bar is usable at mobile width (inputs and buttons stack, no horizontal page scroll).
- [ ] `pytest` passes in full.
- [ ] CLAUDE.md documents the Step 6 date filter and the helpers' new optional arguments.
