import pytest
import requests

import app as gateway_app

NS = "http://leafline.example.com/soap"
ENV = "http://schemas.xmlsoap.org/soap/envelope/"


def envelope(op):
    return (f'<soapenv:Envelope xmlns:soapenv="{ENV}" xmlns:ns="{NS}"><soapenv:Body>'
            f"<ns:{op}/></soapenv:Body></soapenv:Envelope>")


class FakeUpstream:
    """Records the request the proxy forwards and returns a canned response."""

    def __init__(self, content=b"<ok/>", status=200, content_type="text/xml"):
        self.sent = None
        self.content, self.status, self.content_type = content, status, content_type

    def __call__(self, method, url, **kwargs):
        self.sent = {"method": method, "url": url, **kwargs}
        return type("R", (), {"content": self.content, "status_code": self.status,
                              "headers": {"Content-Type": self.content_type}})()


@pytest.fixture()
def upstream(monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(gateway_app.requests, "request", fake)
    return fake


def test_index_lists_wsdl_urls(client):
    data = client.get("/soap/").get_json()
    assert set(data) == {"catalog", "auth", "orders"}
    assert data["catalog"].endswith("/soap/catalog/?wsdl")


def test_post_is_forwarded_to_the_right_service(client, upstream):
    r = client.post("/soap/orders/", data=envelope("ViewCart"),
                    headers={"Content-Type": "text/xml", "SOAPAction": "ViewCart"})
    assert r.status_code == 200 and r.data == b"<ok/>"
    assert upstream.sent["url"] == "http://order-service:5003/soap/"
    assert upstream.sent["headers"] == {"Content-Type": "text/xml", "SOAPAction": "ViewCart"}


@pytest.mark.parametrize("name,base", [("catalog", "http://catalog-service:5001"),
                                       ("auth", "http://auth-service:5002")])
def test_wsdl_address_is_rewritten_to_the_gateway(client, monkeypatch, name, base):
    fake = FakeUpstream(content=f'<soap:address location="{base}/soap/"/>'.encode())
    monkeypatch.setattr(gateway_app.requests, "request", fake)
    r = client.get(f"/soap/{name}/?wsdl", base_url="http://shop.test:5000")
    assert f"http://shop.test:5000/soap/{name}/".encode() in r.data and base.encode() not in r.data
    assert fake.sent["params"].get("wsdl") is not None


def test_trailing_slash_is_optional(client, upstream):
    assert client.get("/soap/catalog?wsdl", follow_redirects=True).status_code == 200


@pytest.mark.parametrize("op", ["ReserveStock", "ReleaseStock", "ValidateToken"])
def test_internal_operations_are_blocked(client, upstream, op):
    r = client.post("/soap/catalog/", data=envelope(op))
    assert r.status_code == 403 and b"Client.Forbidden" in r.data
    assert upstream.sent is None                                  # never reached the service


def test_public_operations_are_not_blocked(client, upstream):
    assert client.post("/soap/catalog/", data=envelope("GetProduct")).status_code == 200


def test_malformed_xml_is_forwarded_so_the_service_can_fault(client, upstream):
    assert client.post("/soap/catalog/", data=b"<<not xml").status_code == 200
    assert upstream.sent is not None


def test_xml_without_a_body_is_not_treated_as_internal(client, upstream):
    assert client.post("/soap/catalog/", data=b"<a/>").status_code == 200


def test_unknown_service(client):
    r = client.get("/soap/nope/?wsdl")
    assert r.status_code == 404 and b"Client.UnknownService" in r.data


def test_unreachable_service_returns_503_fault(client, monkeypatch):
    def refuse(*a, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(gateway_app.requests, "request", refuse)
    r = client.post("/soap/auth/", data=envelope("Login"))
    assert r.status_code == 503 and b"Server.UpstreamUnavailable" in r.data
