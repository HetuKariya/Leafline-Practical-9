"""Catalog SOAP service (Spyne, SOAP 1.1).

Public operations : ListCategories, SearchProducts, GetProduct, CheckStock
Internal operations: ReserveStock, ReleaseStock  (called by order-service; blocked at the gateway)
"""
from spyne import Application, ServiceBase, rpc, Integer, Unicode, Float, Boolean, Array, Fault
from spyne.model.complex import ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication

from db import session

TNS = "http://leafline.example.com/soap"
PAGE_SIZE = 12


class ProductSummary(ComplexModel):
    __namespace__ = TNS
    id = Integer
    name = Unicode
    category = Unicode
    price = Float


class ProductPage(ComplexModel):
    __namespace__ = TNS
    page = Integer
    page_size = Integer
    total = Integer
    products = Array(ProductSummary)


class Product(ComplexModel):
    __namespace__ = TNS
    id = Integer
    name = Unicode
    description = Unicode
    category = Unicode
    price = Float
    stock = Integer


class CategoryList(ComplexModel):
    __namespace__ = TNS
    count = Integer
    categories = Array(Unicode)


class StockStatus(ComplexModel):
    __namespace__ = TNS
    product_id = Integer
    requested = Integer
    available = Integer
    in_stock = Boolean


def client_fault(code, message):
    return Fault(faultcode=f"Client.{code}", faultstring=message)


def _row_or_fault(conn, product_id, columns="*"):
    row = conn.execute(f"SELECT {columns} FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise client_fault("ProductNotFound", f"No product with id {product_id}.")
    return row


class CatalogService(ServiceBase):
    # ---- public operations
    @rpc(_returns=CategoryList)
    def ListCategories(ctx):
        with session() as conn:
            rows = conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
        return CategoryList(count=len(rows), categories=[r["category"] for r in rows])

    @rpc(Unicode, Unicode, Integer, _returns=ProductPage)
    def SearchProducts(ctx, query, category, page):
        query, category = (query or "").strip(), (category or "").strip()
        page = max(page or 1, 1)
        where, args = [], []
        if query:
            where.append("name LIKE ?")
            args.append(f"%{query}%")
        if category:
            where.append("category=?")
            args.append(category)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with session() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM products {clause}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT id,name,category,price FROM products {clause} ORDER BY id LIMIT ? OFFSET ?",
                args + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        return ProductPage(page=page, page_size=PAGE_SIZE, total=total,
                           products=[ProductSummary(**dict(r)) for r in rows])

    @rpc(Integer, _returns=Product)
    def GetProduct(ctx, product_id):
        with session() as conn:
            row = _row_or_fault(conn, product_id)
        return Product(**dict(row))

    @rpc(Integer, Integer, _returns=StockStatus)
    def CheckStock(ctx, product_id, qty):
        qty = qty or 1
        with session() as conn:
            row = _row_or_fault(conn, product_id, "stock")
        return StockStatus(product_id=product_id, requested=qty, available=row["stock"],
                           in_stock=row["stock"] >= qty)

    # ---- internal operations (order-service only)
    @rpc(Integer, Integer, _returns=StockStatus)
    def ReserveStock(ctx, product_id, qty):
        if qty is None or qty < 1:
            raise client_fault("InvalidInput", "qty must be at least 1.")
        with session() as conn:
            row = _row_or_fault(conn, product_id, "name")
            cur = conn.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?",
                               (qty, product_id, qty))
            if cur.rowcount == 0:
                raise client_fault("OutOfStock", f"{row['name']} is out of stock.")
            left = conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()[0]
        return StockStatus(product_id=product_id, requested=qty, available=left, in_stock=True)

    @rpc(Integer, Integer, _returns=StockStatus)
    def ReleaseStock(ctx, product_id, qty):
        if qty is None or qty < 1:
            raise client_fault("InvalidInput", "qty must be at least 1.")
        with session() as conn:
            _row_or_fault(conn, product_id, "id")
            conn.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, product_id))
            left = conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()[0]
        return StockStatus(product_id=product_id, requested=qty, available=left, in_stock=True)


soap_application = Application(
    [CatalogService],
    tns=TNS,
    name="CatalogService",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)
soap_wsgi = WsgiApplication(soap_application)
