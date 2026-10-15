import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "bootstrap.db")

import pytest  # noqa: E402

import db  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auth.db"))
    db.init_db()


@pytest.fixture()
def client():
    return flask_app.test_client()
