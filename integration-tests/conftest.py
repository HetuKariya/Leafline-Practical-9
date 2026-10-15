import os
import secrets
import time

import pytest
import requests
from zeep import Client

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:5000").rstrip("/")
TNS = "http://leafline.example.com/soap"


@pytest.fixture(scope="session", autouse=True)
def stack_is_up():
    """Wait (up to 60 s) for the gateway; fail with a clear message if the stack is down."""
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if requests.get(f"{GATEWAY}/health", timeout=3).ok:
                return
        except requests.RequestException:
            time.sleep(2)
    pytest.exit(f"Gateway not reachable at {GATEWAY}. Start the stack with: docker compose up -d", 2)


@pytest.fixture(scope="session")
def catalog():
    return Client(f"{GATEWAY}/soap/catalog/?wsdl")


@pytest.fixture(scope="session")
def auth():
    return Client(f"{GATEWAY}/soap/auth/?wsdl")


@pytest.fixture(scope="session")
def orders():
    return Client(f"{GATEWAY}/soap/orders/?wsdl")


@pytest.fixture()
def new_user(auth):
    email = f"it{secrets.token_hex(4)}@example.com"
    return email, auth.service.Register(email=email, password="secret123")


@pytest.fixture()
def auth_header(orders, new_user):
    return [orders.get_element(f"{{{TNS}}}AuthHeader")(token=new_user[1].token)]
