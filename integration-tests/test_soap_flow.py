"""End-to-end SOAP tests. They talk to the running docker-compose stack through the gateway,
using Zeep (a real SOAP client), so they exercise: WSDL generation, the gateway proxy, the
SOAP header, SOAP Faults, and service-to-service SOAP calls (order -> auth, order -> catalog).
"""
import secrets

import pytest
import requests
from zeep.exceptions import Fault

from conftest import GATEWAY, TNS


# ------------------------------------------------------------------ WSDL / proxy
@pytest.mark.parametrize("service", ["catalog", "auth", "orders"])
def test_wsdl_is_served_through_gateway(service):
    r = requests.get(f"{GATEWAY}/soap/{service}/?wsdl", timeout=10)
    assert r.status_code == 200
    assert "definitions" in r.text
    assert f"/soap/{service}/" in r.text          # address was rewritten to the gateway URL


def test_unknown_service_returns_fault():
    r = requests.get(f"{GATEWAY}/soap/nope/?wsdl", timeout=10)
    assert r.status_code == 404 and "Client.UnknownService" in r.text


@pytest.mark.parametrize("op", ["ReserveStock", "ReleaseStock"])
def test_internal_operations_are_blocked(op):
    envelope = (f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns="{TNS}"><soapenv:Body><ns:{op}><ns:product_id>1</ns:product_id>'
                f'<ns:qty>1</ns:qty></ns:{op}></soapenv:Body></soapenv:Envelope>')
    r = requests.post(f"{GATEWAY}/soap/catalog/", data=envelope,
                      headers={"Content-Type": "text/xml", "SOAPAction": op}, timeout=10)
    assert r.status_code == 403 and "Client.Forbidden" in r.text


# ------------------------------------------------------------------ catalog service
def test_catalog_operations(catalog):
    cats = catalog.service.ListCategories()
    assert cats.count == 4 and "succulent" in cats.categories.string

    page = catalog.service.SearchProducts(query="Monstera", category="", page=1)
    assert page.total > 0 and page.products.ProductSummary[0].name.startswith("Monstera")

    product = catalog.service.GetProduct(product_id=1)
    assert product.id == 1 and product.price > 0

    assert catalog.service.CheckStock(product_id=1, qty=5).in_stock is True


def test_unknown_product_is_a_soap_fault(catalog):
    with pytest.raises(Fault) as exc:
        catalog.service.GetProduct(product_id=99999)
    assert exc.value.code.split(":")[-1] == "Client.ProductNotFound"


# ------------------------------------------------------------------ auth service
def test_register_login_and_duplicate(auth, new_user):
    email, _ = new_user
    assert auth.service.Login(email=email, password="secret123").token
    with pytest.raises(Fault) as exc:
        auth.service.Register(email=email, password="secret123")
    assert exc.value.code.split(":")[-1] == "Client.EmailTaken"


def test_bad_credentials_fault(auth, new_user):
    with pytest.raises(Fault) as exc:
        auth.service.Login(email=new_user[0], password="wrong-password")
    assert exc.value.code.split(":")[-1] == "Client.BadCredentials"


# ------------------------------------------------------------------ order service (header + cross-service)
def test_protected_operation_without_header_faults(orders):
    with pytest.raises(Fault) as exc:
        orders.service.ViewCart()
    assert exc.value.code.split(":")[-1] == "Client.Unauthorized"


def test_invalid_token_faults(orders):
    bad = [orders.get_element(f"{{{TNS}}}AuthHeader")(token="not-a-real-token")]
    with pytest.raises(Fault) as exc:
        orders.service.ViewCart(_soapheaders=bad)
    assert exc.value.code.split(":")[-1] == "Client.Unauthorized"


def test_empty_cart_checkout_faults(orders, auth_header):
    with pytest.raises(Fault) as exc:
        orders.service.Checkout(_soapheaders=auth_header)
    assert exc.value.code.split(":")[-1] == "Client.EmptyCart"


def test_full_checkout_flow_updates_stock(catalog, orders, auth_header):
    before = catalog.service.CheckStock(product_id=2, qty=1).available

    orders.service.AddToCart(product_id=1, qty=2, _soapheaders=auth_header)
    cart = orders.service.AddToCart(product_id=2, qty=3, _soapheaders=auth_header)
    assert cart.item_count == 5 and len(cart.items.CartItem) == 2

    receipt = orders.service.Checkout(_soapheaders=auth_header)
    assert receipt.order_id and receipt.total == pytest.approx(cart.total)

    # catalog's stock changed because order-service called ReserveStock over SOAP
    assert catalog.service.CheckStock(product_id=2, qty=1).available == before - 3
    assert orders.service.ListOrders(_soapheaders=auth_header).count == 1
    assert orders.service.ViewCart(_soapheaders=auth_header).item_count == 0


def test_add_unknown_product_faults(orders, auth_header):
    with pytest.raises(Fault) as exc:
        orders.service.AddToCart(product_id=99999, qty=1, _soapheaders=auth_header)
    assert exc.value.code.split(":")[-1] == "Client.ProductNotFound"


def test_remove_from_cart(orders, auth_header):
    orders.service.AddToCart(product_id=1, qty=1, _soapheaders=auth_header)
    assert orders.service.RemoveFromCart(product_id=1, _soapheaders=auth_header).item_count == 0


# ------------------------------------------------------------------ REST facade (REST -> SOAP)
def test_rest_api_translates_to_soap():
    assert requests.get(f"{GATEWAY}/api/products?page=1", timeout=10).json()["total"] == 60
    assert requests.get(f"{GATEWAY}/api/products/99999", timeout=10).status_code == 404

    email = f"rest{secrets.token_hex(3)}@example.com"
    reg = requests.post(f"{GATEWAY}/api/register", json={"email": email, "password": "secret123"}, timeout=10)
    assert reg.status_code == 201
    h = {"Authorization": "Bearer " + reg.json()["token"]}
    assert requests.post(f"{GATEWAY}/api/cart", json={"product_id": 1, "qty": 1}, headers=h, timeout=10).status_code == 201
    out = requests.post(f"{GATEWAY}/api/checkout", headers=h, timeout=10)
    assert out.status_code == 201 and out.json()["order_id"]
    assert requests.get(f"{GATEWAY}/api/cart", timeout=10).status_code == 401
