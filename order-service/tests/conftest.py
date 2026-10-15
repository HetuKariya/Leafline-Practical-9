import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "bootstrap.db")

import pytest  # noqa: E402

import clients  # noqa: E402
import db  # noqa: E402
from app import app as flask_app  # noqa: E402


class FakeAuth:
    """Stands in for auth-service: two known tokens, everything else is Unauthorized."""

    def __init__(self):
        self.tokens = {"tok-1": 1, "tok-2": 2}
        self.down = False

    def validate(self, token):
        if self.down:
            raise clients.UpstreamError("Server.UpstreamUnavailable", "auth-service is down")
        if token not in self.tokens:
            raise clients.UpstreamError("Client.Unauthorized", "Missing or invalid token.")
        return self.tokens[token]


class FakeCatalog:
    """Stands in for catalog-service and records every call so tests can assert on them."""

    def __init__(self):
        self.products = {1: ("Monstera #1", 10.0), 2: ("Fiddle Leaf Fig #2", 25.5), 3: ("Pothos #3", 7.25)}
        self.stock = {1: 100, 2: 100, 3: 100}
        self.calls = []
        self.down = False

    def get_product(self, product_id):
        if self.down:
            raise clients.UpstreamError("Server.UpstreamUnavailable", "catalog-service is down")
        if product_id not in self.products:
            raise clients.UpstreamError("Client.ProductNotFound", f"No product with id {product_id}.")
        name, price = self.products[product_id]
        return {"id": product_id, "name": name, "price": price}

    def reserve(self, product_id, qty):
        self.calls.append(("reserve", product_id, qty))
        if self.down:
            raise clients.UpstreamError("Server.UpstreamUnavailable", "catalog-service is down")
        if self.stock[product_id] < qty:
            raise clients.UpstreamError("Client.OutOfStock", f"{self.products[product_id][0]} is out of stock.")
        self.stock[product_id] -= qty

    def release(self, product_id, qty):
        self.calls.append(("release", product_id, qty))
        if self.down:
            raise clients.UpstreamError("Server.UpstreamUnavailable", "catalog-service is down")
        self.stock[product_id] += qty


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "orders.db"))
    db.init_db()


@pytest.fixture(autouse=True)
def fake_auth(monkeypatch):
    fake = FakeAuth()
    monkeypatch.setattr(clients, "auth", fake)
    return fake


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    fake = FakeCatalog()
    monkeypatch.setattr(clients, "catalog", fake)
    return fake


@pytest.fixture()
def client():
    return flask_app.test_client()
