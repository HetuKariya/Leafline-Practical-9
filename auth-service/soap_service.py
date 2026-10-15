"""Auth SOAP service (Spyne, SOAP 1.1).

Public operations  : Register, Login      -> return a session token
Internal operation : ValidateToken        -> used by order-service (blocked at the gateway)
"""
import secrets
import sqlite3

from spyne import Application, ServiceBase, rpc, Integer, Unicode, Fault
from spyne.model.complex import ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from werkzeug.security import check_password_hash, generate_password_hash

from db import session

TNS = "http://leafline.example.com/soap"
HASH_METHOD = "pbkdf2:sha256:20000"   # light hashing on purpose (same as the original project)


class AuthResult(ComplexModel):
    __namespace__ = TNS
    email = Unicode
    token = Unicode


class TokenInfo(ComplexModel):
    __namespace__ = TNS
    user_id = Integer
    email = Unicode


def client_fault(code, message):
    return Fault(faultcode=f"Client.{code}", faultstring=message)


def clean_credentials(email, password):
    return (email or "").strip().lower(), password or ""


def issue_token(conn, user_id):
    token = secrets.token_hex(16)
    conn.execute("INSERT INTO tokens(token,user_id) VALUES(?,?)", (token, user_id))
    return token


class AuthService(ServiceBase):
    @rpc(Unicode, Unicode, _returns=AuthResult)
    def Register(ctx, email, password):
        email, password = clean_credentials(email, password)
        if "@" not in email or len(password) < 6:
            raise client_fault("InvalidInput",
                               "Enter a valid email and a password of at least 6 characters.")
        with session() as conn:
            try:
                cur = conn.execute("INSERT INTO users(email,password_hash) VALUES(?,?)",
                                   (email, generate_password_hash(password, method=HASH_METHOD)))
            except sqlite3.IntegrityError:
                raise client_fault("EmailTaken", "That email is already registered.")
            return AuthResult(email=email, token=issue_token(conn, cur.lastrowid))

    @rpc(Unicode, Unicode, _returns=AuthResult)
    def Login(ctx, email, password):
        email, password = clean_credentials(email, password)
        with session() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user or not check_password_hash(user["password_hash"], password):
                raise client_fault("BadCredentials", "Wrong email or password.")
            return AuthResult(email=email, token=issue_token(conn, user["id"]))

    @rpc(Unicode, _returns=TokenInfo)
    def ValidateToken(ctx, token):
        token = (token or "").strip()
        with session() as conn:
            row = conn.execute(
                "SELECT u.id, u.email FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",
                (token,)).fetchone()
        if not row:
            raise client_fault("Unauthorized", "Missing or invalid token.")
        return TokenInfo(user_id=row["id"], email=row["email"])


soap_application = Application(
    [AuthService],
    tns=TNS,
    name="AuthService",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)
soap_wsgi = WsgiApplication(soap_application)
