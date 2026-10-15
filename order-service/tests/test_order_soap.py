import db
from tests.soap_helpers import soap_call

T1, T2 = "tok-1", "tok-2"


def add(client, pid, qty, token=T1):
    return soap_call(client, "AddToCart", {"product_id": pid, "qty": qty}, token=token)


def test_health_and_wsdl(client):
    assert client.get("/health").get_json()["service"] == "order-service"
    wsdl = client.get("/soap/?wsdl").get_data(as_text=True)
    for op in ("ViewCart", "AddToCart", "RemoveFromCart", "Checkout", "ListOrders", "AuthHeader"):
        assert op in wsdl


# ------------------------------------------------------------------ SOAP header authentication
def test_every_operation_requires_the_auth_header(client):
    for op, params in [("ViewCart", {}), ("AddToCart", {"product_id": 1, "qty": 1}),
                       ("RemoveFromCart", {"product_id": 1}), ("Checkout", {}), ("ListOrders", {})]:
        reply = soap_call(client, op, params)           # no SOAP header at all
        assert reply.fault_code == "Client.Unauthorized", op


def test_blank_or_unknown_token_is_unauthorized(client):
    assert soap_call(client, "ViewCart", token="   ").fault_code == "Client.Unauthorized"
    assert soap_call(client, "ViewCart", token="forged").fault_code == "Client.Unauthorized"


def test_auth_service_outage_surfaces_as_server_fault(client, fake_auth):
    fake_auth.down = True
    assert soap_call(client, "ViewCart", token=T1).fault_code == "Server.UpstreamUnavailable"


# ------------------------------------------------------------------ cart
def test_new_cart_is_empty(client):
    reply = soap_call(client, "ViewCart", token=T1)
    assert reply.number("item_count") == 0 and reply.number("total") == 0 and reply.all("CartItem") == []


def test_add_to_cart_snapshots_name_and_price_and_totals(client):
    add(client, 1, 2)
    reply = add(client, 2, 1)
    assert reply.number("item_count") == 3 and reply.number("total") == 45.5
    assert [e.text for e in reply.all("name")] == ["Monstera #1", "Fiddle Leaf Fig #2"]


def test_adding_the_same_product_accumulates_quantity(client):
    add(client, 1, 2)
    reply = add(client, 1, 3)
    assert len(reply.all("CartItem")) == 1 and reply.number("qty") == 5 and reply.number("line_total") == 50


def test_qty_defaults_to_one_when_omitted(client):
    reply = soap_call(client, "AddToCart", {"product_id": 3}, token=T1)
    assert reply.number("qty") == 1


def test_qty_must_be_between_1_and_20(client):
    assert add(client, 1, 0).fault_code == "Client.InvalidInput"
    assert add(client, 1, 21).fault_code == "Client.InvalidInput"
    assert not add(client, 1, 20).is_fault


def test_add_unknown_product_is_rejected_by_catalog(client):
    assert add(client, 999, 1).fault_code == "Client.ProductNotFound"


def test_catalog_outage_while_adding(client, fake_catalog):
    fake_catalog.down = True
    assert add(client, 1, 1).fault_code == "Server.UpstreamUnavailable"


def test_remove_from_cart(client):
    add(client, 1, 2)
    add(client, 2, 1)
    reply = soap_call(client, "RemoveFromCart", {"product_id": 1}, token=T1)
    assert reply.number("item_count") == 1 and reply.text("name") == "Fiddle Leaf Fig #2"
    assert soap_call(client, "RemoveFromCart", {"product_id": 1}, token=T1).number("item_count") == 1  # no-op


def test_carts_are_private_per_user(client):
    add(client, 1, 2, token=T1)
    assert soap_call(client, "ViewCart", token=T2).number("item_count") == 0


# ------------------------------------------------------------------ checkout
def test_checkout_creates_order_reserves_stock_and_clears_cart(client, fake_catalog):
    add(client, 1, 2)
    add(client, 2, 1)
    reply = soap_call(client, "Checkout", token=T1)
    assert not reply.is_fault and reply.number("order_id") == 1 and reply.number("total") == 45.5
    assert fake_catalog.stock[1] == 98 and fake_catalog.stock[2] == 99
    assert soap_call(client, "ViewCart", token=T1).number("item_count") == 0
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 2


def test_checkout_empty_cart_faults(client):
    assert soap_call(client, "Checkout", token=T1).fault_code == "Client.EmptyCart"


def test_second_checkout_of_same_cart_faults(client):
    add(client, 1, 1)
    soap_call(client, "Checkout", token=T1)
    assert soap_call(client, "Checkout", token=T1).fault_code == "Client.EmptyCart"   # no double order


def test_out_of_stock_rolls_back_reservations_and_restores_cart(client, fake_catalog):
    add(client, 1, 2)
    add(client, 2, 5)
    fake_catalog.stock[2] = 1                                  # second line cannot be satisfied
    reply = soap_call(client, "Checkout", token=T1)
    assert reply.fault_code == "Client.OutOfStock"
    assert fake_catalog.stock[1] == 100                        # first line was given back
    assert ("release", 1, 2) in fake_catalog.calls
    cart = soap_call(client, "ViewCart", token=T1)
    assert cart.number("item_count") == 7                      # cart restored
    assert soap_call(client, "ListOrders", token=T1).number("count") == 0   # no order recorded


def test_catalog_outage_during_checkout_restores_cart(client, fake_catalog):
    add(client, 1, 1)
    fake_catalog.down = True
    assert soap_call(client, "Checkout", token=T1).fault_code == "Server.UpstreamUnavailable"
    assert soap_call(client, "ViewCart", token=T1).number("item_count") == 1


def test_database_failure_after_reserving_compensates(client, fake_catalog):
    add(client, 1, 3)
    with db.session() as conn:
        conn.execute("DROP TABLE orders")                      # make step 3 (record the order) blow up
    reply = soap_call(client, "Checkout", token=T1)
    assert reply.is_fault and reply.fault_code.startswith("Server")
    assert fake_catalog.stock[1] == 100                        # stock released
    assert soap_call(client, "ViewCart", token=T1).number("item_count") == 3   # cart restored


def test_release_failure_during_compensation_is_swallowed(client, fake_catalog):
    add(client, 1, 1)
    add(client, 2, 5)
    fake_catalog.stock[2] = 0
    original_release = fake_catalog.release

    def failing_release(pid, qty):
        original_release(pid, qty)
        from clients import UpstreamError
        raise UpstreamError("Server.UpstreamUnavailable", "release failed")

    fake_catalog.release = failing_release
    assert soap_call(client, "Checkout", token=T1).fault_code == "Client.OutOfStock"


# ------------------------------------------------------------------ order history
def test_list_orders_newest_first_and_private(client):
    for pid in (1, 2):
        add(client, pid, 1)
        soap_call(client, "Checkout", token=T1)
    reply = soap_call(client, "ListOrders", token=T1)
    assert reply.number("count") == 2
    assert [int(e.text) for e in reply.all("order_id")] == [2, 1]
    assert reply.text("created_at").endswith("Z")
    assert soap_call(client, "ListOrders", token=T2).number("count") == 0
