"""Unit tests for the SOAP client wrappers (no network: Zeep's Client is replaced by a stub)."""
import pytest
import requests
from types import SimpleNamespace
from zeep.exceptions import Fault as ZeepFault, TransportError

import clients


class StubService:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def __getattr__(self, name):
        def call(**kwargs):
            return self.behaviour(name, kwargs)
        return call


def stub_client(monkeypatch, behaviour):
    created = []

    def factory(wsdl, transport=None):
        created.append(wsdl)
        return SimpleNamespace(service=StubService(behaviour))

    monkeypatch.setattr(clients, "Client", factory)
    return created


def test_fault_code_normalisation():
    assert clients.fault_code(ZeepFault("m", code="soap11env:Client.ProductNotFound")) == "Client.ProductNotFound"
    assert clients.fault_code(ZeepFault("m", code="{http://x}Client.Oops")) == "Client.Oops"
    assert clients.fault_code(ZeepFault("m", code="Boom")) == "Server.Boom"
    assert clients.fault_code(ZeepFault("m", code=None)) == "Server.Fault"


def test_client_is_built_lazily_once(monkeypatch):
    created = stub_client(monkeypatch, lambda op, kw: SimpleNamespace(user_id=7))
    auth = clients.AuthClient("http://auth/?wsdl")
    assert created == []                                   # nothing built yet
    assert auth.validate("t") == 7 and auth.validate("t") == 7
    assert created == ["http://auth/?wsdl"]                # built exactly once


def test_soap_fault_becomes_upstream_error(monkeypatch):
    def boom(op, kw):
        raise ZeepFault("No product", code="soap11env:Client.ProductNotFound")
    stub_client(monkeypatch, boom)
    with pytest.raises(clients.UpstreamError) as exc:
        clients.CatalogClient("w").get_product(1)
    assert exc.value.code == "Client.ProductNotFound" and exc.value.message == "No product"


@pytest.mark.parametrize("error", [requests.ConnectionError("refused"), TransportError("503"), OSError("dns")])
def test_network_failures_become_unavailable(monkeypatch, error):
    def boom(op, kw):
        raise error
    stub_client(monkeypatch, boom)
    with pytest.raises(clients.UpstreamError) as exc:
        clients.CatalogClient("w").reserve(1, 1)
    assert exc.value.code == "Server.UpstreamUnavailable"


def test_catalog_client_wraps_each_operation(monkeypatch):
    seen = []

    def behaviour(op, kw):
        seen.append((op, kw))
        return SimpleNamespace(id=4, name="Pothos #4", price=9.5)

    stub_client(monkeypatch, behaviour)
    catalog = clients.CatalogClient("w")
    assert catalog.get_product(4) == {"id": 4, "name": "Pothos #4", "price": 9.5}
    catalog.reserve(4, 2)
    catalog.release(4, 2)
    assert [s[0] for s in seen] == ["GetProduct", "ReserveStock", "ReleaseStock"]
    assert seen[1][1] == {"product_id": 4, "qty": 2}
