"""Unit tests for the Zeep wrapper that turns REST calls into SOAP calls (Zeep is stubbed)."""
from types import SimpleNamespace

import pytest
import requests
from zeep.exceptions import Fault as ZeepFault, TransportError

import soap_clients
from soap_clients import Backend, SoapError, _Service, _items


def test_soap_error_status_mapping():
    assert SoapError("Client.Unauthorized", "x").status == 401
    assert SoapError("Client.ProductNotFound", "x").status == 404
    assert SoapError("Client.EmailTaken", "x").status == 409
    assert SoapError("Server.Unexpected", "x").status == 500


def test_items_handles_none_empty_and_populated_arrays():
    assert _items(None, "CartItem") == []
    assert _items(SimpleNamespace(), "CartItem") == []
    assert _items(SimpleNamespace(CartItem=[{"qty": 1}, {"qty": 2}]), "CartItem") == [{"qty": 1}, {"qty": 2}]


class StubClient:
    def __init__(self, behaviour):
        self.service = SimpleNamespace(**{n: self._make(n, behaviour) for n in ("Op", "Broken")})
        self.elements = []

    @staticmethod
    def _make(name, behaviour):
        return lambda **kw: behaviour(name, kw)

    def get_element(self, qname):
        def build(token):
            return ("header", qname, token)
        return build


def service_with(monkeypatch, behaviour):
    stub = StubClient(behaviour)
    created = []
    monkeypatch.setattr(soap_clients, "Client", lambda wsdl, transport=None: created.append(wsdl) or stub)
    return _Service("http://svc/?wsdl"), created


def test_call_builds_client_once_and_sends_header_only_with_token(monkeypatch):
    seen = []
    svc, created = service_with(monkeypatch, lambda op, kw: seen.append(kw) or "result")
    assert svc.call("Op", a=1) == "result"
    svc.call("Op", token="abc", a=2)
    assert created == ["http://svc/?wsdl"]
    assert "_soapheaders" not in seen[0]
    assert seen[1]["_soapheaders"] == [("header", "{http://leafline.example.com/soap}AuthHeader", "abc")]


def test_soap_fault_is_translated(monkeypatch):
    def boom(op, kw):
        raise ZeepFault("Wrong email or password.", code="soap11env:Client.BadCredentials")
    svc, _ = service_with(monkeypatch, boom)
    with pytest.raises(SoapError) as exc:
        svc.call("Op")
    assert exc.value.code == "Client.BadCredentials" and exc.value.status == 401


def test_fault_without_code_defaults_to_server_fault(monkeypatch):
    def boom(op, kw):
        raise ZeepFault("odd", code=None)
    svc, _ = service_with(monkeypatch, boom)
    with pytest.raises(SoapError) as exc:
        svc.call("Op")
    assert exc.value.code == "Server.Fault" and exc.value.status == 500


@pytest.mark.parametrize("error", [requests.ConnectionError("x"), TransportError("y"), OSError("z")])
def test_network_errors_map_to_503(monkeypatch, error):
    def boom(op, kw):
        raise error
    svc, _ = service_with(monkeypatch, boom)
    with pytest.raises(SoapError) as exc:
        svc.call("Op")
    assert exc.value.status == 503


class FakeService:
    def __init__(self, result=None):
        self.result, self.calls = result, []

    def call(self, op, **kw):
        self.calls.append((op, kw))
        return self.result


def make_backend(**services):
    b = Backend()
    for name, svc in services.items():
        setattr(b, name, svc)
    return b


def test_backend_catalog_methods():
    page = SimpleNamespace(products=SimpleNamespace(ProductSummary=[{"id": 1}]), page=2, total=60)
    b = make_backend(catalog=FakeService(page))
    assert b.search_products("fern", "indoor", 2) == {"products": [{"id": 1}], "page": 2, "total": 60}
    assert b.catalog.calls[0] == ("SearchProducts", {"query": "fern", "category": "indoor", "page": 2})
    b.catalog.result = {"id": 3, "name": "Pothos"}
    assert b.get_product(3) == {"id": 3, "name": "Pothos"}


def test_backend_auth_methods():
    b = make_backend(auth=FakeService(SimpleNamespace(token="t", email="a@b.co")))
    assert b.register("a@b.co", "pw") == {"token": "t", "email": "a@b.co"}
    assert b.login("a@b.co", "pw") == {"token": "t", "email": "a@b.co"}
    assert [c[0] for c in b.auth.calls] == ["Register", "Login"]


def test_backend_cart_and_order_methods_reshape_results():
    cart = SimpleNamespace(items=SimpleNamespace(CartItem=[
        {"product_id": 4, "name": "Pothos", "price": 5.0, "qty": 2, "line_total": 10.0}]), total=10.0)
    b = make_backend(orders=FakeService(cart))
    expected = {"items": [{"id": 4, "name": "Pothos", "price": 5.0, "qty": 2}], "total": 10.0}
    assert b.view_cart("t") == expected
    assert b.add_to_cart("t", 4, 2) == expected
    assert b.remove_from_cart("t", 4) == expected
    assert b.orders.calls[1] == ("AddToCart", {"token": "t", "product_id": 4, "qty": 2})

    b.orders.result = SimpleNamespace(order_id=9, total=10.0)
    assert b.checkout("t") == {"order_id": 9, "total": 10.0}

    b.orders.result = SimpleNamespace(orders=SimpleNamespace(OrderSummary=[
        {"order_id": 9, "total": 10.0, "created_at": "2026-10-15T00:00:00Z"}]))
    assert b.list_orders("t") == {"orders": [{"id": 9, "total": 10.0, "created_at": "2026-10-15T00:00:00Z"}]}
