# Spec: Login and Logout

## Overview
Step 3 lets people sign in and sign out. Step 2 created accounts with hashed passwords but never logged anyone in. Now `POST /login` checks the submitted email and password against the `users` table and stores the user's identity in Flask's signed session cookie. `GET /logout` clears that session. The nav in `base.html` changes with login state: a signed-in user sees their name and a "Sign out" link instead of "Sign in" / "Get started". Session-based identity is what every later step needs: profile (Step 4) and adding, editing and deleting expenses (Steps 7–9) all depend on knowing who the current user is.

## Depends on
- **Step 1 (Database setup):** the `users` table, `get_db()`, and the seeded demo user `demo@spendly.com` / `demo123`.
- **Step 2 (Registration):** `get_user_by_email()`, werkzeug password hashing in `create_user()`, flash message rendering in `base.html`, the existing `login.html` template, and `app.secret_key`, which is already set from `SPENDLY_SECRET_KEY`.

## Routes
- `GET /login` — renders the sign-in form (already exists; unchanged apart from the template fixes below) — public
- `POST /login` — validates credentials, starts a session, flashes "Welcome back, <name>!" and redirects to `url_for('landing')` — public
- `GET /logout` — clears the session, flashes "You've been signed out." and redirects to `url_for('landing')` — public. Calling it when nobody is signed in is safe: it clears an empty session and redirects the same way.

`POST /login` behaviour:
- Normalise the email with `.strip().lower()`, the same way registration does. Do **not** strip or otherwise change the password.
- If email or password is empty, re-render `login.html` with status 200 and the error `"Please enter your email and password."`.
- Look up the user with `get_user_by_email()` and verify with `check_password_hash(user["password_hash"], password)`.
- If the user is unknown **or** the password is wrong, re-render `login.html` with status 200 and the **same** generic error, `"Invalid email or password."`. Never reveal which of the two was wrong.
- Do **not** apply the 8-character registration minimum at login. The seeded demo password `demo123` is 7 characters and must still work.
- On success: call `session.clear()` first (to prevent session fixation), then set `session["user_id"] = user["id"]` and `session["user_name"] = user["name"]`, flash `"Welcome back, <name>!"` with category `"success"`, and redirect (302) to `url_for('landing')`.
- When the login fails, pass the normalised email back to the template so the field stays filled in. Never pass the password back.

## Database changes
No database changes. The `users` table already has `id`, `name`, `email` (UNIQUE) and `password_hash`, and `get_user_by_email()` already returns all of them.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html`:
    - change the hardcoded `action="/login"` to `action="{{ url_for('login') }}"`
    - add `value="{{ email or '' }}"` to the email input
    - keep the existing `auth-error` block for showing `error`
  - `templates/base.html`: make the nav session-aware.
    - When `session.user_id` is set, show the user's name (`session.user_name`, auto-escaped) and a "Sign out" link to `url_for('logout')`.
    - Otherwise, show the existing "Sign in" and "Get started" links.

## Files to change
- `app.py`:
  - import `session` from flask
  - add `methods=["GET", "POST"]` to `/login` and implement the POST logic
  - replace the `/logout` stub string with the real logout logic
  - keep any small validation helper inside `app.py`, following the `_validate_registration` pattern
- `database/db.py`: add a `verify_user(email, password)` helper. It returns the user row when the credentials match and `None` otherwise, using `get_user_by_email` and `check_password_hash`. This keeps password checking out of the route.
- `templates/login.html`: as described above.
- `templates/base.html`: as described above.
- `static/css/style.css`: add minimal styles for the signed-in nav, such as a `.nav-user` name label, using CSS variables only.
- `CLAUDE.md`: update the route table to mark `GET/POST /login` and `GET /logout` as implemented (Step 3).

## Files to create
- `tests/test_login_logout.py`: tests covering every Definition of done item below.

## New dependencies
No new dependencies. `check_password_hash` comes from `werkzeug.security`, and werkzeug is already pinned at 3.1.6.

## Rules for implementation
- No SQLAlchemy or ORMs.
- Parameterised queries only (`?` placeholders). Never build SQL with f-strings.
- Passwords are hashed with werkzeug and verified with `werkzeug.security.check_password_hash`. Never compare hashes or plaintext directly.
- Use CSS variables and never hardcode hex values in new CSS. Leave the existing `#f5c6c2` in `.auth-error` alone; it is out of scope.
- All templates extend `base.html`.
- DB access lives in `database/db.py` only. Routes call helpers and never call `get_db()` directly.
- Use `url_for()` for every internal link and form action. No hardcoded paths.
- Use one generic error message for an unknown email and a wrong password, so the form doesn't reveal which accounts exist.
- Call `session.clear()` before setting session keys on login.
- Store only `user_id` and `user_name` in the session. Never store the password or the hash.
- Use `abort()` for HTTP errors. Validation errors re-render the form with status 200, matching the registration pattern.
- Out of scope:
  - "Remember me"
  - password reset
  - rate limiting
  - a `login_required` decorator or protecting routes, which arrives with Step 4 (Profile)
  - signing users in automatically after registration
- Don't implement the `/profile` or `/expenses/*` stubs.
- Logout stays `GET` to match the CLAUDE.md route table.
- The app stays on port 5001.

## Definition of done
- [ ] `GET /login` returns 200 and shows email and password inputs. The form action in the template source uses `url_for('login')`.
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects (302) to `/`. After following the redirect, "Welcome back, Demo User!" is shown.
- [ ] After signing in, the session contains `user_id` (the demo user's id) and `user_name`, and not the password or the hash.
- [ ] Signing in with `  DEMO@Spendly.com ` (mixed case, surrounding spaces) succeeds.
- [ ] A user registered through `/register` can then sign in with the same credentials.
- [ ] A wrong password returns 200 with "Invalid email or password." and no session is set.
- [ ] An unknown email returns 200 with exactly the same "Invalid email or password." message.
- [ ] An empty email or empty password returns 200 with "Please enter your email and password."
- [ ] After a failed login, the email field keeps the submitted email and the password field is empty.
- [ ] When signed out, the nav shows "Sign in" and "Get started". When signed in, it shows the user's name and a "Sign out" link, and not "Sign in".
- [ ] `GET /logout` clears the session, redirects (302) to `/` and flashes "You've been signed out." Afterwards, the nav shows "Sign in" again.
- [ ] `GET /logout` without being signed in still redirects to `/` without an error.
- [ ] `/logout` no longer returns the raw stub string.
- [ ] The new nav CSS contains no hex values.
- [ ] `verify_user()` returns the row for valid credentials and `None` for a wrong password or an unknown email.
- [ ] A signed-in user who requests `/login` or `/register` (GET or POST) is redirected (302) to `/`, and the session is unchanged.
- [ ] `pytest` passes, including the existing registration tests.
- [ ] The CLAUDE.md route table shows `/login` and `/logout` as implemented in Step 3.
