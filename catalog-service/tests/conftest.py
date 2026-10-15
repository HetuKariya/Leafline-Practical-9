import os
import tempfile

# Must be set before `app` is imported (app.py seeds the database at import time).
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "bootstrap.db")

import pytest  # noqa: E402

import db  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own freshly seeded database (60 plants, stock 1,000,000)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "catalog.db"))
    db.init_db()


@pytest.fixture()
def client():
    return flask_app.test_client()


@pytest.fixture()
def set_stock():
    def _set(product_id, stock):
        with db.session() as conn:
            conn.execute("UPDATE products SET stock=? WHERE id=?", (stock, product_id))
    return _set


@pytest.fixture()
def stock_of():
    def _get(product_id):
        with db.session() as conn:
            return conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()[0]
    return _get
