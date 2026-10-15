"""Readable demo of the whole SOAP flow (the original test_client.py, updated for microservices).

    GATEWAY_URL=http://localhost:5000 python smoke_client.py
"""
import os
import secrets

from zeep import Client
from zeep.exceptions import Fault

G = os.environ.get("GATEWAY_URL", "http://localhost:5000").rstrip("/")
TNS = "http://leafline.example.com/soap"


def main():
    catalog = Client(f"{G}/soap/catalog/?wsdl").service
    auth = Client(f"{G}/soap/auth/?wsdl").service
    order_client = Client(f"{G}/soap/orders/?wsdl")
    orders = order_client.service

    print("== catalog-service ==")
    cats = catalog.ListCategories()
    print(f"Categories ({cats.count}):", cats.categories.string)
    page = catalog.SearchProducts(query="Monstera", category="", page=1)
    print(f"Search 'Monstera': {page.total} matches")
    print("GetProduct(1):", catalog.GetProduct(product_id=1).name)
    try:
        catalog.GetProduct(product_id=99999)
    except Fault as e:
        print("SOAP Fault:", e.code, "-", e.message)

    print("\n== auth-service ==")
    email = f"student{secrets.token_hex(3)}@example.com"
    token = auth.Register(email=email, password="secret123").token
    print("Registered:", email)

    print("\n== order-service (token travels in a SOAP header) ==")
    headers = [order_client.get_element(f"{{{TNS}}}AuthHeader")(token=token)]
    orders.AddToCart(product_id=1, qty=2, _soapheaders=headers)
    cart = orders.AddToCart(product_id=4, qty=1, _soapheaders=headers)
    print(f"Cart: {cart.item_count} items, total ${cart.total:.2f}")
    receipt = orders.Checkout(_soapheaders=headers)
    print(f"Checkout OK: order #{receipt.order_id}, total ${receipt.total:.2f}")
    try:
        orders.ViewCart()
    except Fault as e:
        print("SOAP Fault:", e.code, "-", e.message)


if __name__ == "__main__":
    main()
