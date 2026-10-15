"""Leafline gateway: storefront + REST API + SOAP console + SOAP reverse proxy.

The REST API translates every request into SOAP calls to the microservices.
The proxy exposes each service's raw SOAP endpoint:  /soap/<catalog|auth|orders>/  (+ ?wsdl).
"""
import os
import time

import requests
from flask import Flask, Response, jsonify, render_template, request
from lxml import etree

import soap_clients
from soap_clients import SoapError

app = Flask(__name__)

UPSTREAMS = {
    "catalog": os.environ.get("CATALOG_URL", "http://catalog-service:5001"),
    "auth": os.environ.get("AUTH_URL", "http://auth-service:5002"),
    "orders": os.environ.get("ORDER_URL", "http://order-service:5003"),
}
# Service-to-service operations that must never be reachable from outside.
INTERNAL_OPS = {"ReserveStock", "ReleaseStock", "ValidateToken"}
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"


def error(msg, code=400):
    return jsonify(error=msg), code


@app.errorhandler(SoapError)
def soap_error(exc):
    return error(exc.message, exc.status)


def token():
    return request.headers.get("Authorization", "").removeprefix("Bearer ").strip()


# ---------- pages ----------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/soap-console")
def soap_console():
    return render_template("soap.html")


@app.get("/health")
def health():
    return jsonify(status="ok", service="gateway", time=time.time())


# ---------- REST API (-> SOAP) ----------
@app.get("/api/products")
def list_products():
    try:
        page = max(int(request.args.get("page", 1) or 1), 1)
    except ValueError:
        return error("page must be a number.", 422)
    return jsonify(soap_clients.backend.search_products(
        request.args.get("q", "").strip(), request.args.get("category", "").strip(), page))


@app.get("/api/products/<int:pid>")
def get_product(pid):
    return jsonify(soap_clients.backend.get_product(pid))


def credentials():
    data = request.get_json(silent=True) or {}
    return str(data.get("email", "")).strip().lower(), str(data.get("password", ""))


@app.post("/api/register")
def register():
    email, password = credentials()
    return jsonify(soap_clients.backend.register(email, password)), 201


@app.post("/api/login")
def login():
    email, password = credentials()
    return jsonify(soap_clients.backend.login(email, password))


@app.get("/api/cart")
def get_cart():
    return jsonify(soap_clients.backend.view_cart(token()))


@app.post("/api/cart")
def add_to_cart():
    data = request.get_json(silent=True) or {}
    pid, qty = data.get("product_id"), data.get("qty", 1)
    if not isinstance(pid, int) or not isinstance(qty, int) or not 1 <= qty <= 20:
        return error("Send a product_id and a qty between 1 and 20.", 422)
    return jsonify(soap_clients.backend.add_to_cart(token(), pid, qty)), 201


@app.delete("/api/cart/<int:pid>")
def remove_from_cart(pid):
    return jsonify(soap_clients.backend.remove_from_cart(token(), pid))


@app.post("/api/checkout")
def checkout():
    return jsonify(soap_clients.backend.checkout(token())), 201


@app.get("/api/orders")
def orders():
    return jsonify(soap_clients.backend.list_orders(token()))


# ---------- SOAP reverse proxy ----------
@app.get("/soap/")
def soap_index():
    base = request.host_url.rstrip("/")
    return jsonify({name: f"{base}/soap/{name}/?wsdl" for name in UPSTREAMS})


def soap_fault_xml(code, message):
    return (f'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="{SOAP_ENV}"><soap:Body>'
            f"<soap:Fault><faultcode>{code}</faultcode><faultstring>{message}</faultstring>"
            "</soap:Fault></soap:Body></soap:Envelope>")


def requested_operation(body):
    """Local name of the first element inside <Body>, or None if the XML is not a SOAP envelope."""
    try:
        root = etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True))
        node = root.find(f"{{{SOAP_ENV}}}Body")
        return etree.QName(node[0]).localname if node is not None and len(node) else None
    except (etree.XMLSyntaxError, ValueError):
        return None


@app.route("/soap/<name>/", methods=["GET", "POST"], strict_slashes=False)
def soap_proxy(name):
    base = UPSTREAMS.get(name)
    if base is None:
        return Response(soap_fault_xml("Client.UnknownService", f"No SOAP service named {name}."),
                        404, mimetype="text/xml")
    body = request.get_data()
    if request.method == "POST" and requested_operation(body) in INTERNAL_OPS:
        return Response(soap_fault_xml("Client.Forbidden", "This operation is internal."),
                        403, mimetype="text/xml")
    headers = {h: request.headers[h] for h in ("Content-Type", "SOAPAction") if h in request.headers}
    try:
        up = requests.request(request.method, f"{base}/soap/", params=request.args, data=body,
                              headers=headers, timeout=20)
    except requests.RequestException as exc:
        return Response(soap_fault_xml("Server.UpstreamUnavailable", f"{name} is unreachable: {exc}"),
                        503, mimetype="text/xml")
    content = up.content
    if request.method == "GET" and "wsdl" in request.args:
        # The service advertises its internal address; point clients at the gateway instead.
        content = content.replace(f"{base}/soap/".encode(),
                                  f"{request.host_url}soap/{name}/".encode())
    return Response(content, up.status_code, content_type=up.headers.get("Content-Type", "text/xml"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
