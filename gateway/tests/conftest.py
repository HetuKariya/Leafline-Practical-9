import pytest

import app as gateway_app
import soap_clients
from soap_clients import SoapError


class FakeBackend:
    """Replaces soap_clients.backend so REST routes can be tested without any microservice."""

    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    def search_products(self, q, category, page):
        self._rec("search_products", q, category, page)
        return {"products": [{"id": 1, "name": "Monstera #1", "category": "indoor", "price": 9.0}],
                "page": page, "total": 1}

    def get_product(self, pid):
        self._rec("get_product", pid)
        if pid == 404:
            raise SoapError("Client.ProductNotFound", f"No product with id {pid}.")
        return {"id": pid, "name": "Monstera #1"}

    def register(self, email, password):
        self._rec("register", email, password)
        if email == "taken@example.com":
            raise SoapError("Client.EmailTaken", "That email is already registered.")
        if "@" not in email:
            raise SoapError("Client.InvalidInput", "Enter a valid email.")
        return {"token": "tok", "email": email}

    def login(self, email, password):
        self._rec("login", email, password)
        if password != "secret123":
            raise SoapError("Client.BadCredentials", "Wrong email or password.")
        return {"token": "tok", "email": email}

    def view_cart(self, token):
        self._rec("view_cart", token)
        if token != "tok":
            raise SoapError("Client.Unauthorized", "Login required.")
        return {"items": [], "total": 0.0}

    def add_to_cart(self, token, pid, qty):
        self._rec("add_to_cart", token, pid, qty)
        return {"items": [{"id": pid, "name": "x", "price": 1.0, "qty": qty}], "total": float(qty)}

    def remove_from_cart(self, token, pid):
        self._rec("remove_from_cart", token, pid)
        return {"items": [], "total": 0.0}

    def checkout(self, token):
        self._rec("checkout", token)
        if token == "empty":
            raise SoapError("Client.EmptyCart", "Your cart is empty.")
        if token == "out":
            raise SoapError("Client.OutOfStock", "Pothos is out of stock.")
        if token == "down":
            raise SoapError("Server.UpstreamUnavailable", "order-service unreachable")
        if token == "weird":
            raise SoapError("Server.Whatever", "unexpected")
        return {"order_id": 1, "total": 10.0}

    def list_orders(self, token):
        self._rec("list_orders", token)
        return {"orders": [{"id": 1, "total": 10.0, "created_at": "2026-10-15T00:00:00Z"}]}


@pytest.fixture()
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(soap_clients, "backend", fake)
    return fake


@pytest.fixture()
def client():
    return gateway_app.app.test_client()
