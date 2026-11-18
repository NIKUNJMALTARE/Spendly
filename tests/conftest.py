import os
import shutil
import tempfile

import pytest

# Must run before `app` is imported: app.py calls init_db()/seed_db() at import
# time. Assign directly (not setdefault) so tests never touch the real database.
_IMPORT_DB_DIR = tempfile.mkdtemp(prefix="spendly-test-")
os.environ["SPENDLY_DB_PATH"] = os.path.join(_IMPORT_DB_DIR, "import.db")
os.environ.setdefault("SPENDLY_SECRET_KEY", "test-secret")

import database.db as db_module  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_import_db():
    yield
    shutil.rmtree(_IMPORT_DB_DIR, ignore_errors=True)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Fresh, seeded database per test. pytest-flask builds `client` from this."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    db_module.seed_db()
    flask_app.config.update(TESTING=True)
    yield flask_app
