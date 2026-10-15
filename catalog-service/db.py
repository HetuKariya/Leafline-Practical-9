"""SQLite access for the catalog service (it owns the `products` table only)."""
import os
import sqlite3
from contextlib import contextmanager

PLANTS = ["Monstera", "Fiddle Leaf Fig", "Snake Plant", "Pothos", "ZZ Plant", "Rubber Plant",
          "Calathea", "Peace Lily", "Aloe Vera", "Boston Fern"]
CATEGORIES = ["indoor", "succulent", "hanging", "large"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
  category TEXT NOT NULL, price REAL NOT NULL, stock INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category);
"""


def db_path():
    # Read at call time so tests (and Docker) can change it via the environment.
    return os.environ.get("DB_PATH", "catalog.db")


@contextmanager
def session():
    conn = sqlite3.connect(db_path(), timeout=30, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with session() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            rows = []
            for i in range(60):
                name = f"{PLANTS[i % len(PLANTS)]} #{i + 1}"
                rows.append((name, f"A healthy {name.lower()} in a 6-inch pot.",
                             CATEGORIES[i % len(CATEGORIES)], round(9 + (i * 3.7) % 60, 2), 1_000_000))
            conn.executemany(
                "INSERT INTO products(name,description,category,price,stock) VALUES(?,?,?,?,?)", rows)
