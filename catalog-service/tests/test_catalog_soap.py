import db
from tests.soap_helpers import soap_call


# ------------------------------------------------------------------ infrastructure
def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["service"] == "catalog-service"


def test_wsdl_advertises_all_operations(client):
    r = client.get("/soap/?wsdl")
    assert r.status_code == 200
    for op in ("ListCategories", "SearchProducts", "GetProduct", "CheckStock",
               "ReserveStock", "ReleaseStock"):
        assert f'name="{op}"' in r.get_data(as_text=True)


def test_malformed_request_is_rejected_by_schema_validation(client):
    reply = soap_call(client, "GetProduct", {"product_id": "not-a-number"})
    assert reply.is_fault and "Client" in reply.fault_code


def test_init_db_is_idempotent_and_does_not_reseed():
    db.init_db()
    db.init_db()
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 60


# ------------------------------------------------------------------ ListCategories
def test_list_categories(client):
    reply = soap_call(client, "ListCategories")
    assert not reply.is_fault
    assert reply.number("count") == 4
    assert sorted(e.text for e in reply.all("string")) == ["hanging", "indoor", "large", "succulent"]


# ------------------------------------------------------------------ SearchProducts
def test_search_first_page_has_twelve_of_sixty(client):
    reply = soap_call(client, "SearchProducts", {"query": "", "category": "", "page": 1})
    assert reply.number("total") == 60 and reply.number("page_size") == 12
    assert len(reply.all("ProductSummary")) == 12


def test_search_last_page_and_page_past_the_end(client):
    last = soap_call(client, "SearchProducts", {"page": 5})
    assert len(last.all("ProductSummary")) == 12
    beyond = soap_call(client, "SearchProducts", {"page": 6})
    assert beyond.all("ProductSummary") == [] and beyond.number("total") == 60


def test_search_page_defaults_to_one_and_clamps_zero(client):
    assert soap_call(client, "SearchProducts", {}).number("page") == 1
    assert soap_call(client, "SearchProducts", {"page": 0}).number("page") == 1


def test_search_by_name_is_case_insensitive_and_trimmed(client):
    reply = soap_call(client, "SearchProducts", {"query": "  monstera ", "category": "", "page": 1})
    names = [e.text for e in reply.all("name")]
    assert reply.number("total") == 6 and all(n.startswith("Monstera") for n in names)


def test_search_by_category(client):
    reply = soap_call(client, "SearchProducts", {"query": "", "category": "succulent", "page": 1})
    assert reply.number("total") == 15
    assert {e.text for e in reply.all("category")} == {"succulent"}


def test_search_combined_filters_and_no_match(client):
    combo = soap_call(client, "SearchProducts", {"query": "Monstera", "category": "indoor", "page": 1})
    assert combo.number("total") >= 1
    none = soap_call(client, "SearchProducts", {"query": "cactus-that-does-not-exist", "page": 1})
    assert none.number("total") == 0 and none.all("ProductSummary") == []


# ------------------------------------------------------------------ GetProduct / CheckStock
def test_get_product_returns_all_fields(client):
    reply = soap_call(client, "GetProduct", {"product_id": 1})
    assert reply.number("id") == 1 and reply.text("name") == "Monstera #1"
    assert reply.number("price") > 0 and reply.number("stock") == 1_000_000
    assert "monstera #1" in reply.text("description")


def test_get_unknown_product_is_a_fault(client):
    reply = soap_call(client, "GetProduct", {"product_id": 99999})
    assert reply.is_fault and reply.fault_code == "Client.ProductNotFound"
    assert "99999" in reply.fault_text


def test_check_stock_in_and_out_of_stock(client, set_stock):
    set_stock(3, 2)
    ok = soap_call(client, "CheckStock", {"product_id": 3, "qty": 2})
    assert ok.text("in_stock") == "true" and ok.number("available") == 2
    short = soap_call(client, "CheckStock", {"product_id": 3, "qty": 3})
    assert short.text("in_stock") == "false" and short.number("requested") == 3


def test_check_stock_defaults_qty_to_one_and_unknown_faults(client):
    assert soap_call(client, "CheckStock", {"product_id": 1}).number("requested") == 1
    reply = soap_call(client, "CheckStock", {"product_id": 99999, "qty": 1})
    assert reply.fault_code == "Client.ProductNotFound"


# ------------------------------------------------------------------ ReserveStock / ReleaseStock
def test_reserve_stock_decrements(client, set_stock, stock_of):
    set_stock(5, 10)
    reply = soap_call(client, "ReserveStock", {"product_id": 5, "qty": 4})
    assert not reply.is_fault and reply.number("available") == 6
    assert stock_of(5) == 6


def test_reserve_more_than_available_faults_and_changes_nothing(client, set_stock, stock_of):
    set_stock(5, 3)
    reply = soap_call(client, "ReserveStock", {"product_id": 5, "qty": 4})
    assert reply.fault_code == "Client.OutOfStock" and "out of stock" in reply.fault_text
    assert stock_of(5) == 3


def test_reserve_validates_input_and_product(client):
    assert soap_call(client, "ReserveStock", {"product_id": 1, "qty": 0}).fault_code == "Client.InvalidInput"
    assert soap_call(client, "ReserveStock", {"product_id": 1}).fault_code == "Client.InvalidInput"
    assert soap_call(client, "ReserveStock", {"product_id": 99999, "qty": 1}).fault_code == "Client.ProductNotFound"


def test_release_stock_restores_units(client, set_stock, stock_of):
    set_stock(7, 10)
    soap_call(client, "ReserveStock", {"product_id": 7, "qty": 6})
    reply = soap_call(client, "ReleaseStock", {"product_id": 7, "qty": 6})
    assert reply.number("available") == 10 and stock_of(7) == 10


def test_release_validates_input_and_product(client):
    assert soap_call(client, "ReleaseStock", {"product_id": 1, "qty": -1}).fault_code == "Client.InvalidInput"
    assert soap_call(client, "ReleaseStock", {"product_id": 99999, "qty": 1}).fault_code == "Client.ProductNotFound"
