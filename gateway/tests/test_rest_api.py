AUTH = {"Authorization": "Bearer tok"}


def test_pages_and_health(client):
    assert client.get("/health").get_json()["service"] == "gateway"
    assert "Leafline" in client.get("/").get_data(as_text=True)
    console = client.get("/soap-console").get_data(as_text=True)
    assert "SOAP console" in console and "/soap/${OPS[op].svc}/" in console


def test_list_products_passes_filters_and_page(client, backend):
    r = client.get("/api/products?q=%20fern%20&category=indoor&page=3")
    assert r.status_code == 200 and r.get_json()["total"] == 1
    assert backend.calls[-1] == ("search_products", "fern", "indoor", 3)


def test_list_products_defaults_and_bad_page(client, backend):
    client.get("/api/products")
    assert backend.calls[-1] == ("search_products", "", "", 1)
    client.get("/api/products?page=0")
    assert backend.calls[-1][3] == 1
    assert client.get("/api/products?page=abc").status_code == 422


def test_get_product_and_not_found_maps_to_404(client, backend):
    assert client.get("/api/products/5").get_json()["id"] == 5
    r = client.get("/api/products/404")
    assert r.status_code == 404 and "No product" in r.get_json()["error"]


def test_register_login_status_codes(client, backend):
    ok = client.post("/api/register", json={"email": " New@Example.com ", "password": "secret123"})
    assert ok.status_code == 201 and backend.calls[-1] == ("register", "new@example.com", "secret123")
    assert client.post("/api/register", json={"email": "taken@example.com", "password": "secret123"}).status_code == 409
    assert client.post("/api/register", json={"email": "bad", "password": "x"}).status_code == 422
    assert client.post("/api/register").status_code == 422             # no JSON body at all
    assert client.post("/api/login", json={"email": "a@b.co", "password": "secret123"}).status_code == 200
    assert client.post("/api/login", json={"email": "a@b.co", "password": "nope"}).status_code == 401


def test_cart_requires_token_and_forwards_it(client, backend):
    assert client.get("/api/cart").status_code == 401
    assert client.get("/api/cart", headers=AUTH).status_code == 200
    assert backend.calls[-1] == ("view_cart", "tok")


def test_add_to_cart_validation(client, backend):
    assert client.post("/api/cart", json={"product_id": 1, "qty": 2}, headers=AUTH).status_code == 201
    assert backend.calls[-1] == ("add_to_cart", "tok", 1, 2)
    client.post("/api/cart", json={"product_id": 1}, headers=AUTH)
    assert backend.calls[-1][-1] == 1                                   # qty defaults to 1
    for bad in ({"product_id": "1", "qty": 1}, {"product_id": 1, "qty": 0},
                {"product_id": 1, "qty": 21}, {"qty": 1}, {"product_id": 1, "qty": "2"}):
        assert client.post("/api/cart", json=bad, headers=AUTH).status_code == 422


def test_remove_from_cart(client, backend):
    assert client.delete("/api/cart/9", headers=AUTH).status_code == 200
    assert backend.calls[-1] == ("remove_from_cart", "tok", 9)


def test_checkout_success_and_fault_status_mapping(client, backend):
    assert client.post("/api/checkout", headers=AUTH).status_code == 201
    expectations = {"empty": 400, "out": 409, "down": 503, "weird": 500}
    for token, status in expectations.items():
        r = client.post("/api/checkout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == status, token
        assert "error" in r.get_json()


def test_list_orders(client, backend):
    r = client.get("/api/orders", headers=AUTH)
    assert r.status_code == 200 and r.get_json()["orders"][0]["id"] == 1
