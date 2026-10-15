"""SOAP clients (Zeep) used by the gateway's REST API to talk to the three microservices."""
import os
import threading

import requests
from zeep import Client
from zeep.exceptions import Fault as ZeepFault, TransportError
from zeep.helpers import serialize_object
from zeep.transports import Transport

TNS = "http://leafline.example.com/soap"
CATALOG_WSDL = os.environ.get("CATALOG_WSDL", "http://catalog-service:5001/soap/?wsdl")
AUTH_WSDL = os.environ.get("AUTH_WSDL", "http://auth-service:5002/soap/?wsdl")
ORDER_WSDL = os.environ.get("ORDER_WSDL", "http://order-service:5003/soap/?wsdl")

STATUS_BY_FAULT = {
    "Unauthorized": 401, "BadCredentials": 401, "ProductNotFound": 404, "EmailTaken": 409,
    "InvalidInput": 422, "EmptyCart": 400, "OutOfStock": 409, "UpstreamUnavailable": 503,
}


class SoapError(Exception):
    """A SOAP Fault translated into something the REST layer can return."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message
        self.status = STATUS_BY_FAULT.get(code.split(".")[-1], 500)


def _items(array, element):
    """Spyne arrays arrive as <Array>.<ItemType>; an empty array arrives as None."""
    if array is None:
        return []
    return [serialize_object(i, dict) for i in (getattr(array, element, None) or [])]


class _Service:
    def __init__(self, wsdl):
        self.wsdl, self._client, self._lock = wsdl, None, threading.Lock()

    def client(self):
        with self._lock:
            if self._client is None:
                self._client = Client(self.wsdl, transport=Transport(timeout=5, operation_timeout=20))
        return self._client

    def call(self, operation, token=None, **kwargs):
        try:
            client = self.client()
            if token:
                header = client.get_element(f"{{{TNS}}}AuthHeader")(token=token)
                kwargs["_soapheaders"] = [header]
            return getattr(client.service, operation)(**kwargs)
        except ZeepFault as exc:
            code = str(exc.code or "Server.Fault").split("}")[-1].split(":")[-1]
            raise SoapError(code, exc.message)
        except (requests.RequestException, TransportError, OSError) as exc:
            raise SoapError("Server.UpstreamUnavailable", f"{operation} failed: {exc}")


class Backend:
    """One method per REST route; returns plain dicts/lists ready for jsonify."""

    def __init__(self):
        self.catalog, self.auth, self.orders = _Service(CATALOG_WSDL), _Service(AUTH_WSDL), _Service(ORDER_WSDL)

    # ---- catalog
    def search_products(self, q, category, page):
        r = self.catalog.call("SearchProducts", query=q, category=category, page=page)
        return {"products": _items(r.products, "ProductSummary"), "page": r.page, "total": r.total}

    def get_product(self, product_id):
        return serialize_object(self.catalog.call("GetProduct", product_id=product_id), dict)

    # ---- auth
    def register(self, email, password):
        r = self.auth.call("Register", email=email, password=password)
        return {"token": r.token, "email": r.email}

    def login(self, email, password):
        r = self.auth.call("Login", email=email, password=password)
        return {"token": r.token, "email": r.email}

    # ---- cart / orders
    @staticmethod
    def _cart(r):
        items = [{"id": i["product_id"], "name": i["name"], "price": i["price"], "qty": i["qty"]}
                 for i in _items(r.items, "CartItem")]
        return {"items": items, "total": r.total}

    def view_cart(self, token):
        return self._cart(self.orders.call("ViewCart", token=token))

    def add_to_cart(self, token, product_id, qty):
        return self._cart(self.orders.call("AddToCart", token=token, product_id=product_id, qty=qty))

    def remove_from_cart(self, token, product_id):
        return self._cart(self.orders.call("RemoveFromCart", token=token, product_id=product_id))

    def checkout(self, token):
        r = self.orders.call("Checkout", token=token)
        return {"order_id": r.order_id, "total": r.total}

    def list_orders(self, token):
        r = self.orders.call("ListOrders", token=token)
        return {"orders": [{"id": o["order_id"], "total": o["total"], "created_at": o["created_at"]}
                           for o in _items(r.orders, "OrderSummary")]}


backend = Backend()
