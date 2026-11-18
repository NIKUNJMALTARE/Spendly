# Spec: Profile Page Design

## Overview
Step 4 replaces the `/profile` stub with a real, signed-in-only page and builds its visual design. The page has four parts: a user info card (avatar initials, name, email, member-since date), a row of summary stats (total spent, number of transactions, top category), a recent-transactions table, and a spending-by-category breakdown. This step is about **layout and design**: the user info card shows the real signed-in user, but the stats, transactions and category breakdown use hardcoded placeholder data passed from the route. A later step replaces that placeholder data with real queries against the `expenses` table. Step 4 also adds the first access control in the app: signed-out visitors who request `/profile` are sent to `/login`. The signed-in nav gets a link to the profile page.

## Depends on
- **Step 1 (Database setup):** the `users` table (`id`, `name`, `email`, `created_at`), `get_db()`, and the seeded demo user `demo@spendly.com` / `demo123`.
- **Step 2 (Registration):** a way to create new users to view the page as.
- **Step 3 (Login and Logout):** `session["user_id"]` / `session["user_name"]`, the session-aware nav in `base.html`, and flash message rendering.

## Routes
- `GET /profile` — renders `profile.html` for the signed-in user — logged-in
- `POST /login` (changed) — on success, redirect to `url_for('profile')` instead of `url_for('landing')`
- `GET/POST /login` and `GET/POST /register` (changed) — a signed-in user is redirected to `url_for('profile')` instead of `/`
- `GET /logout` — unchanged, still redirects to `/`

`GET /profile` behaviour:
- If `session.get("user_id")` is not set, flash `"Please sign in to view your profile."` with category `"error"` and redirect (302) to `url_for('login')`.
- Load the user row with a new `get_user_by_id(user_id)` helper.
- If the session points to a user that no longer exists, call `session.clear()` and redirect to `url_for('login')`. Don't raise a 500.
- Build the placeholder data (stats, recent transactions, category breakdown) as module-level constants in `app.py` and pass them to the template together with the user row. The route itself only fetches and renders.
- Use `₹` as the currency symbol, matching the landing page.

Placeholder data (values are suggestions; keep them internally consistent):
- `stats`: `total_spent`, `transaction_count`, `top_category`
- `recent_transactions`: 5 items, each with `date`, `description`, `category`, `amount`
- `category_breakdown`: one item per category in `CATEGORIES` that has spending, each with `name`, `amount`, `percent` (whole numbers summing to 100)

## Database changes
No database changes. The `users` table already has every column the profile card needs.

Add one read-only helper to `database/db.py`:
- `get_user_by_id(user_id)` — returns `id, name, email, created_at` for the user, or `None`. **Never select `password_hash`.** Use a `?` placeholder, and close the connection in a `finally` block like `get_user_by_email()` does.

## Templates
- **Create:**
  - `templates/profile.html` — extends `base.html`, sets the title block to `Profile — Spendly`, and loads `profile.css` in the `head` block. Sections:
    1. **User info card:** a circular avatar with the user's initials (computed in Jinja from `user.name`), the name in the display font, the email, and "Member since <Month YYYY>" built from `user.created_at`.
    2. **Summary stats row:** three stat cards: Total spent, Transactions, Top category.
    3. **Recent transactions:** a table with Date, Description, Category (shown as a pill/badge) and Amount (right-aligned). Show an empty-state message if the list is empty.
    4. **Spending by category:** one row per category with its name, a horizontal bar whose width is `percent`%, and the amount.
    - Use semantic markup: `<section>` per block, `<h2>` headings, a real `<table>` with `<thead>`/`<th scope="col">`.
- **Modify:**
  - `templates/base.html`: in the signed-in branch of the nav, make the user's name a link to `url_for('profile')`, keeping the `nav-user` class. Leave the signed-out branch unchanged.

## Files to change
- `app.py`:
  - import `get_user_by_id` from `database.db`
  - add the placeholder data constants in the Helpers section
  - replace the `/profile` stub with the real route described above
- `database/db.py`: add `get_user_by_id()`.
- `templates/base.html`: as described above.
- `CLAUDE.md`: mark `GET /profile` as implemented (Step 4, design with placeholder stats) in the route table and add `get_user_by_id()` to the list of user helpers.

## Files to create
- `templates/profile.html`
- `static/css/profile.css` — page-specific styles for the profile page (CLAUDE.md: page-specific styles go in their own file, not inline `<style>` tags).
- `tests/test_profile.py` — tests covering every Definition of done item below that can be checked through the Flask test client.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only (`?` placeholders). Never build SQL with f-strings.
- Passwords are hashed with werkzeug. This step doesn't touch passwords, and `get_user_by_id()` must never return `password_hash`.
- Use CSS variables and never hardcode hex values. Reuse the existing tokens in `style.css` (`--paper-card`, `--border`, `--accent`, `--accent-light`, `--accent-2`, `--ink-muted`, `--radius-md`, `--font-display`, etc.). If a new token is truly needed, add it to `:root` in `style.css` instead of writing a hex value in `profile.css`.
- All templates extend `base.html`.
- DB access lives in `database/db.py` only. The route calls `get_user_by_id()` and never calls `get_db()` directly.
- Use `url_for()` for every internal link. No hardcoded paths.
- No inline `<style>` tags and no inline `style=""` attributes, **except** the bar width in the category breakdown (`style="width: {{ item.percent }}%"`), which is data-driven and is allowed.
- No JavaScript is needed for this step. If any is added, it must be vanilla JS in `static/js/main.js`.
- The layout must be responsive: stat cards and the two lower sections stack into one column below roughly 768px, and the transactions table doesn't overflow the page on a phone (wrap it in a horizontally scrollable container).
- Auto-escape all user data. Never use `|safe` on `user.name` or `user.email`.
- Out of scope:
  - real expense queries for stats, transactions and categories (a later step)
  - editing the profile, changing the password, or deleting the account
  - date filters
  - a reusable `login_required` decorator: an inline session check in the route is fine for now
- Don't implement the `/expenses/*` stubs.
- The app stays on port 5001.

## Definition of done
- [ ] Signed out, `GET /profile` redirects (302) to `/login` and, after following the redirect, shows "Please sign in to view your profile."
- [ ] Signed in as `demo@spendly.com` / `demo123`, `GET /profile` returns 200 and shows "Demo User", `demo@spendly.com`, and a "Member since" line.
- [ ] The avatar shows the user's initials (e.g. "DU" for Demo User).
- [ ] A newly registered user who signs in sees their own name and email on `/profile`, not the demo user's.
- [ ] The page shows the three stat cards (Total spent, Transactions, Top category) with `₹`-formatted amounts.
- [ ] The recent-transactions table renders with Date, Description, Category and Amount columns and 5 placeholder rows.
- [ ] The category breakdown renders one bar per category, and each bar's width matches its percentage.
- [ ] If the session's `user_id` no longer exists in the database, `/profile` clears the session and redirects to `/login` without a 500 error.
- [ ] `/profile` no longer returns the raw stub string.
- [ ] Signing in redirects (302) to `/profile`, and the page shows "Welcome back, <name>!".
- [ ] A signed-in user who requests `/login` or `/register` is redirected (302) to `/profile`.
- [ ] When signed in, the user's name in the nav links to `/profile`. When signed out, the nav is unchanged.
- [ ] `profile.html` extends `base.html` and loads `static/css/profile.css`. There are no `<style>` tags in the template.
- [ ] `static/css/profile.css` contains no hex colour values.
- [ ] `get_user_by_id()` returns the user row for an existing id, returns `None` for an unknown id, and its result has no `password_hash` key.
- [ ] At a 375px-wide viewport, the page has no horizontal page scroll and the stat cards stack vertically.
- [ ] A user name containing HTML (e.g. `<b>x</b>`) is shown escaped on the profile page.
- [ ] `pytest` passes, including the existing registration and login tests.
- [ ] The CLAUDE.md route table shows `/profile` as implemented in Step 4.
