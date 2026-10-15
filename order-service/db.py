"""SQLite access for the order service (it owns `cart_items`, `orders`, `order_items`).

Product name/price are snapshotted into the cart when an item is added, so the order service
never needs a foreign key into the catalog database.
"""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS cart_items(
  user_id INTEGER NOT NULL, product_id INTEGER NOT NULL, name TEXT NOT NULL,
  price REAL NOT NULL, qty INTEGER NOT NULL, PRIMARY KEY(user_id, product_id));
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, total REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  order_id INTEGER NOT NULL, product_id INTEGER NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL);
"""


def db_path():
    return os.environ.get("DB_PATH", "orders.db")


@contextmanager
def session():
    conn = sqlite3.connect(db_path(), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with session() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
