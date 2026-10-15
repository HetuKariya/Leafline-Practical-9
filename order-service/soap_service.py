"""Order SOAP service (Spyne, SOAP 1.1): cart, checkout and order history.

Every operation needs the `AuthHeader` SOAP header. The token is validated by calling
auth-service over SOAP; stock is reserved by calling catalog-service over SOAP.
"""
import time

from spyne import Application, ServiceBase, rpc, Integer, Unicode, Float, Array, Fault
from spyne.model.complex import ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication

import clients
from db import session

TNS = "http://leafline.example.com/soap"


class AuthHeader(ComplexModel):
    """SOAP header carrying the session token (returned by Login / Register)."""
    __namespace__ = TNS
    token = Unicode


class CartItem(ComplexModel):
    __namespace__ = TNS
    product_id = Integer
    name = Unicode
    price = Float
    qty = Integer
    line_total = Float


class Cart(ComplexModel):
    __namespace__ = TNS
    items = Array(CartItem)
    item_count = Integer
    total = Float


class OrderReceipt(ComplexModel):
    __namespace__ = TNS
    order_id = Integer
    total = Float
    items = Array(CartItem)


class OrderSummary(ComplexModel):
    __namespace__ = TNS
    order_id = Integer
    total = Float
    created_at = Unicode


class OrderList(ComplexModel):
    __namespace__ = TNS
    count = Integer
    orders = Array(OrderSummary)


# -------------------------------------------------------------------- helpers
def client_fault(code, message):
    return Fault(faultcode=f"Client.{code}", faultstring=message)


def to_fault(err):
    """Re-raise a fault from another microservice as our own SOAP Fault."""
    return Fault(faultcode=err.code, faultstring=err.message)


def current_user(ctx):
    header = ctx.in_header
    token = ((header.token if header is not None else "") or "").strip()
    if not token:
        raise client_fault("Unauthorized",
                           "Missing or invalid token. Send the AuthHeader SOAP header "
                           "(token from Login or Register).")
    try:
        return clients.auth.validate(token)
    except clients.UpstreamError as err:
        raise to_fault(err)


def load_cart(conn, user_id):
    rows = conn.execute(
        "SELECT product_id, name, price, qty FROM cart_items WHERE user_id=? ORDER BY product_id",
        (user_id,)).fetchall()
    items = [CartItem(product_id=r["product_id"], name=r["name"], price=r["price"], qty=r["qty"],
                      line_total=round(r["price"] * r["qty"], 2)) for r in rows]
    return Cart(items=items, item_count=sum(i.qty for i in items),
                total=round(sum(i.line_total for i in items), 2))


def put_in_cart(conn, user_id, item):
    conn.execute(
        """INSERT INTO cart_items(user_id,product_id,name,price,qty) VALUES(?,?,?,?,?)
           ON CONFLICT(user_id,product_id) DO UPDATE SET qty=qty+excluded.qty,
                                                         name=excluded.name, price=excluded.price""",
        (user_id, item.product_id, item.name, item.price, item.qty))


def release_stock(reserved):
    """Compensation step: give back stock already reserved (best effort)."""
    for item in reserved:
        try:
            clients.catalog.release(item.product_id, item.qty)
        except clients.UpstreamError:
            pass


# -------------------------------------------------------------------- service
class OrderService(ServiceBase):
    __in_header__ = AuthHeader

    @rpc(_returns=Cart)
    def ViewCart(ctx):
        user_id = current_user(ctx)
        with session() as conn:
            return load_cart(conn, user_id)

    @rpc(Integer, Integer, _returns=Cart)
    def AddToCart(ctx, product_id, qty):
        qty = 1 if qty is None else qty
        if not 1 <= qty <= 20:
            raise client_fault("InvalidInput", "qty must be between 1 and 20.")
        user_id = current_user(ctx)
        try:
            product = clients.catalog.get_product(product_id)     # also proves the product exists
        except clients.UpstreamError as err:
            raise to_fault(err)
        with session() as conn:
            put_in_cart(conn, user_id, CartItem(product_id=product["id"], name=product["name"],
                                                price=product["price"], qty=qty))
            return load_cart(conn, user_id)

    @rpc(Integer, _returns=Cart)
    def RemoveFromCart(ctx, product_id):
        user_id = current_user(ctx)
        with session() as conn:
            conn.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id))
            return load_cart(conn, user_id)

    @rpc(_returns=OrderReceipt)
    def Checkout(ctx):
        user_id = current_user(ctx)

        # 1. Claim the cart atomically (a double-click cannot create two orders).
        with session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cart = load_cart(conn, user_id)
            if not cart.items:
                conn.execute("ROLLBACK")
                raise client_fault("EmptyCart", "Your cart is empty.")
            conn.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))
            conn.execute("COMMIT")

        # 2. Reserve stock in catalog-service; undo everything if any line fails.
        reserved = []
        try:
            for item in cart.items:
                clients.catalog.reserve(item.product_id, item.qty)
                reserved.append(item)
            # 3. Record the order.
            with session() as conn:
                conn.execute("BEGIN IMMEDIATE")
                order_id = conn.execute("INSERT INTO orders(user_id,total,created_at) VALUES(?,?,?)",
                                        (user_id, cart.total, time.time())).lastrowid
                conn.executemany("INSERT INTO order_items VALUES(?,?,?,?)",
                                 [(order_id, i.product_id, i.qty, i.price) for i in cart.items])
                conn.execute("COMMIT")
        except Exception as err:
            release_stock(reserved)
            with session() as conn:
                for item in cart.items:
                    put_in_cart(conn, user_id, item)
            if isinstance(err, clients.UpstreamError):
                raise to_fault(err)
            raise
        return OrderReceipt(order_id=order_id, total=cart.total, items=cart.items)

    @rpc(_returns=OrderList)
    def ListOrders(ctx):
        user_id = current_user(ctx)
        with session() as conn:
            rows = conn.execute(
                "SELECT id,total,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20",
                (user_id,)).fetchall()
        orders = [OrderSummary(order_id=r["id"], total=r["total"],
                               created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["created_at"])))
                  for r in rows]
        return OrderList(count=len(orders), orders=orders)


soap_application = Application(
    [OrderService],
    tns=TNS,
    name="OrderService",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)
soap_wsgi = WsgiApplication(soap_application)
