# Spec: Registration

## Overview
This step turns the static `/register` page into a working sign-up flow. A visitor submits their name, email and password; the app validates the input, hashes the password with werkzeug, stores a new row in the `users` table, and redirects to the sign-in page with a success message. It is the first feature built on the Step 1 data layer and is a prerequisite for login/logout (Step 3) and everything that needs an authenticated user. Logging the new user in automatically is **out of scope** — sessions arrive in Step 3.

## Depends on
- **Step 1 — Database setup**: `users` table (with `UNIQUE` on `email`), `get_db()`, `init_db()`, `seed_db()` in `database/db.py`.

## Routes
- `GET /register` — render the empty registration form (already exists, unchanged behaviour) — public
- `POST /register` — validate input, create the user, flash a success message and redirect to `GET /login`; on validation failure re-render `register.html` with an `error` message and the previously entered name/email — public

Both methods are handled by the existing `register()` view (`methods=["GET", "POST"]`). No other new routes.

## Database changes
No database changes. The existing `users` table (`id`, `name`, `email UNIQUE`, `password_hash`, `created_at`) already covers registration.

New helper functions in `database/db.py` (no schema change):
- `get_user_by_email(email)` — returns the `sqlite3.Row` for that email or `None`.
- `create_user(name, email, password)` — hashes `password` with `generate_password_hash`, inserts the row with a parameterised query, returns the new user's `id`. Lets `sqlite3.IntegrityError` propagate on duplicate email so the route can turn it into a friendly error (guards against the race between the existence check and the insert).
- Both open their own connection via `get_db()` and close it in a `finally` block.

## Templates
- **Create:** none
- **Modify:**
  - `templates/register.html` — change `action="/register"` to `action="{{ url_for('register') }}"`; pre-fill `name` and `email` inputs with `value="{{ name or '' }}"` / `value="{{ email or '' }}"` after a failed submit (never pre-fill password); add `minlength="8"` to the password input.
  - `templates/base.html` — render flashed messages (`get_flashed_messages(with_categories=true)`) inside `<main>` above `{% block content %}`, so the success message shows on the login page after redirect.

## Files to change
- `app.py` — import `request`, `redirect`, `url_for`, `flash`; set `app.secret_key` (read from `SPENDLY_SECRET_KEY` env var with a dev-only fallback) so `flash()` works; change `register()` to accept GET and POST and implement the flow; import `create_user`, `get_user_by_email` from `database.db`.
- `database/db.py` — add `get_user_by_email()` and `create_user()`.
- `templates/register.html` — see Templates.
- `templates/base.html` — see Templates.
- `static/css/style.css` — add `.flash` / `.flash-success` / `.flash-error` styles using existing CSS variables (`--accent`, `--accent-light`, `--danger`, `--danger-light`, `--radius-sm`, etc.).

## Files to create
- `tests/__init__.py` (empty) if needed for test discovery
- `tests/conftest.py` — pytest fixture that points `SPENDLY_DB_PATH` at a temp file *before* importing `app`, and provides a Flask test `client`
- `tests/test_registration.py` — tests covering the Definition of done

## New dependencies
No new dependencies. Uses `flask`, `werkzeug.security` and `pytest` / `pytest-flask`, all already in `requirements.txt`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders) — never f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (`generate_password_hash`) — never store or log plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- All DB access lives in `database/db.py`; `register()` only reads the form, validates, calls the DB helpers, and renders/redirects
- Use `url_for()` for every internal link and form action — no hardcoded URLs
- Normalise email before checking/storing: `.strip().lower()`; strip whitespace from `name`
- Validation rules (server-side, independent of HTML `required`):
  - name: required, non-empty after strip
  - email: required, must contain a single `@` with a non-empty local part and a `.` in the domain
  - password: required, at least 8 characters
  - email must not already exist → error "An account with that email already exists."
- On any validation error re-render `register.html` (HTTP 200) with a single `error` string; do not redirect
- On success: `flash("Account created — please sign in.", "success")` then `redirect(url_for("login"))`
- Do not implement login, sessions, or logout — those are Step 3. Do not touch other stub routes.
- Keep `app.run(debug=True, port=5001)` unchanged

## Definition of done
- [ ] `python app.py` starts on port 5001 without errors
- [ ] `GET /register` renders the form with Full name, Email and Password fields
- [ ] Submitting valid details (e.g. `Test User`, `test@example.com`, `password123`) redirects to `/login` and shows "Account created — please sign in."
- [ ] A new row exists in `users` for that email, and `password_hash` is a werkzeug hash (not the plaintext password); `check_password_hash` validates it
- [ ] Registering with ` Test@Example.com ` (mixed case / whitespace) is stored as `test@example.com`
- [ ] Registering again with an existing email (e.g. `demo@spendly.com`) re-renders the form with "An account with that email already exists." and no new row is inserted
- [ ] Submitting an empty name shows a validation error and inserts nothing
- [ ] Submitting a malformed email (e.g. `not-an-email`) shows a validation error and inserts nothing
- [ ] Submitting a password shorter than 8 characters shows a validation error and inserts nothing
- [ ] After a failed submit, name and email fields keep their values; password is empty
- [ ] The form `action` and the "Sign in" link use `url_for()` (no hardcoded `/register`)
- [ ] Flash message styles use only CSS variables (no hex values added to `style.css`)
- [ ] `pytest` passes, with tests in `tests/test_registration.py` covering success, duplicate email, and each validation error, using an isolated temp database
