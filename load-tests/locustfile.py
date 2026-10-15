"""Load tests for Leafline.

Run the UI:        locust -f locustfile.py --host http://localhost:5000
Run headless:      locust -f locustfile.py --host http://localhost:5000 \
                        --headless -u 100 -r 10 -t 2m --html report.html
Use a load shape:  locust -f locustfile.py,shape.py --host http://localhost:5000
"""
import random
import uuid

from locust import HttpUser, SequentialTaskSet, between, task

CATEGORIES = ["indoor", "succulent", "hanging", "large"]
SEARCH_TERMS = ["monstera", "fern", "aloe", "pothos", "lily", "fig"]
PRODUCT_COUNT = 60


class Browser(HttpUser):
    """Anonymous visitor who only reads the catalog (most of the traffic)."""
    weight = 7
    wait_time = between(1, 4)

    @task(1)
    def home(self):
        self.client.get("/")

    @task(5)
    def list_products(self):
        self.client.get(f"/api/products?page={random.randint(1, 5)}", name="/api/products?page=[n]")

    @task(3)
    def filter_category(self):
        self.client.get(f"/api/products?category={random.choice(CATEGORIES)}", name="/api/products?category=[c]")

    @task(2)
    def search(self):
        self.client.get(f"/api/products?q={random.choice(SEARCH_TERMS)}", name="/api/products?q=[term]")

    @task(4)
    def view_product(self):
        pid = random.randint(1, PRODUCT_COUNT)
        with self.client.get(f"/api/products/{pid}", name="/api/products/[id]", catch_response=True) as r:
            if r.status_code == 200 and r.json().get("id") == pid:
                r.success()
            else:
                r.failure(f"Unexpected response for product {pid}: {r.status_code}")

    @task(1)
    def health(self):
        self.client.get("/health")


class BuyerFlow(SequentialTaskSet):
    """Register -> browse -> add to cart -> checkout -> check orders."""

    def on_start(self):
        self.email = f"user-{uuid.uuid4().hex[:12]}@loadtest.dev"
        self.password = "locust-pass-123"
        self.headers = {}

    @task
    def register(self):
        with self.client.post("/api/register", json={"email": self.email, "password": self.password},
                              catch_response=True) as r:
            if r.status_code == 201 and r.json().get("token"):
                self.headers = {"Authorization": f"Bearer {r.json()['token']}"}
                r.success()
            else:
                r.failure(f"Register failed: {r.status_code} {r.text[:100]}")

    @task
    def browse(self):
        self.client.get("/api/products", name="/api/products?page=[n]")

    @task
    def add_items(self):
        for _ in range(random.randint(1, 3)):
            self.client.post("/api/cart", headers=self.headers, name="/api/cart [add]",
                             json={"product_id": random.randint(1, PRODUCT_COUNT), "qty": random.randint(1, 3)})

    @task
    def view_cart(self):
        with self.client.get("/api/cart", headers=self.headers, catch_response=True) as r:
            if r.status_code == 200 and r.json()["items"]:
                r.success()
            else:
                r.failure("Cart should not be empty")

    @task
    def checkout(self):
        with self.client.post("/api/checkout", headers=self.headers, catch_response=True) as r:
            if r.status_code == 201 and "order_id" in r.json():
                r.success()
            else:
                r.failure(f"Checkout failed: {r.status_code} {r.text[:100]}")

    @task
    def orders(self):
        self.client.get("/api/orders", headers=self.headers)

    @task
    def relogin_and_stop(self):
        self.client.post("/api/login", json={"email": self.email, "password": self.password})
        self.interrupt()  # end the flow; the user starts a fresh one as a new shopper


class Buyer(HttpUser):
    """Signed-in shopper who goes through the full purchase flow."""
    weight = 3
    wait_time = between(1, 3)
    tasks = [BuyerFlow]
