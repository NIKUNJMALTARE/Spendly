import html
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO = {"email": "demo@spendly.com", "password": "demo123"}
SIGN_IN_MESSAGE = "Please sign in to view analytics."
ASSETS = ("corner-accent.svg", "clock-outline.svg", "progress-dots.svg")


def _login(client):
    return client.post("/login", data=DEMO)


def _text(resp):
    return html.unescape(resp.get_data(as_text=True))


# --- Access control ------------------------------------------------- #

def test_signed_out_redirects_to_login(client):
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/login"


def test_signed_out_flash_shown(client):
    resp = client.get("/analytics", follow_redirects=True)
    assert resp.request.path == "/login"
    assert SIGN_IN_MESSAGE in _text(resp)


def test_stale_session_redirects_and_clears(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999_999
        sess["user_name"] = "Ghost"
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert urlparse(resp.headers["Location"]).path == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_signed_in_renders_coming_soon(client):
    _login(client)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    body = _text(resp)
    assert "Advanced Analytics" in body
    assert "Coming soon" in body
    assert "We're crafting something special" in body
    assert "css/analytics.css" in body


# --- Navbar ----------------------------------------------------------- #

def test_nav_link_hidden_when_signed_out(client):
    assert 'href="/analytics"' not in _text(client.get("/"))


def test_nav_link_shown_when_signed_in(client):
    _login(client)
    assert 'href="/analytics"' in _text(client.get("/profile"))


def test_nav_link_active_only_on_analytics(client):
    _login(client)
    analytics_body = _text(client.get("/analytics"))
    profile_body = _text(client.get("/profile"))
    assert 'nav-link-analytics is-active' in analytics_body
    assert 'aria-current="page"' in analytics_body
    assert 'nav-link-analytics is-active' not in profile_body


# --- Assets ----------------------------------------------------------- #

def test_design_assets_exist_and_are_referenced(client):
    _login(client)
    body = _text(client.get("/analytics"))
    for name in ASSETS:
        path = PROJECT_ROOT / "static" / "img" / "analytics" / name
        assert path.stat().st_size > 0
        assert f"img/analytics/{name}" in body
        assert client.get(f"/static/img/analytics/{name}").status_code == 200
    assert "figma.com" not in body
