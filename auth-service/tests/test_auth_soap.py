import db
from tests.soap_helpers import soap_call

PW = "secret123"


def register(client, email="a@example.com", password=PW):
    return soap_call(client, "Register", {"email": email, "password": password})


def test_health_and_wsdl(client):
    assert client.get("/health").get_json()["service"] == "auth-service"
    wsdl = client.get("/soap/?wsdl").get_data(as_text=True)
    for op in ("Register", "Login", "ValidateToken"):
        assert f'name="{op}"' in wsdl


# ------------------------------------------------------------------ Register
def test_register_returns_token_and_normalises_email(client):
    reply = register(client, "  Student@Example.COM ")
    assert not reply.is_fault
    assert reply.text("email") == "student@example.com" and len(reply.text("token")) == 32


def test_register_rejects_invalid_email_and_short_password(client):
    assert register(client, "no-at-sign").fault_code == "Client.InvalidInput"
    assert register(client, "a@example.com", "123").fault_code == "Client.InvalidInput"


def test_register_rejects_missing_fields(client):
    reply = soap_call(client, "Register", {})
    assert reply.fault_code == "Client.InvalidInput"


def test_register_duplicate_email_is_case_insensitive(client):
    register(client, "dup@example.com")
    again = register(client, "DUP@example.com")
    assert again.fault_code == "Client.EmailTaken"


def test_password_is_stored_hashed_not_in_plaintext(client):
    register(client, "hash@example.com")
    with db.session() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored != PW and stored.startswith("pbkdf2:sha256")


# ------------------------------------------------------------------ Login
def test_login_success_issues_a_new_token_each_time(client):
    first = register(client).text("token")
    second = soap_call(client, "Login", {"email": "A@example.com ", "password": PW})
    third = soap_call(client, "Login", {"email": "a@example.com", "password": PW})
    assert not second.is_fault and second.text("token") not in (first, third.text("token"))


def test_login_wrong_password_and_unknown_user_share_one_fault(client):
    register(client)
    wrong = soap_call(client, "Login", {"email": "a@example.com", "password": "nope-nope"})
    unknown = soap_call(client, "Login", {"email": "ghost@example.com", "password": PW})
    assert wrong.fault_code == unknown.fault_code == "Client.BadCredentials"
    assert wrong.fault_text == unknown.fault_text          # does not reveal which emails exist


# ------------------------------------------------------------------ ValidateToken (internal)
def test_validate_token_returns_user(client):
    token = register(client, "val@example.com").text("token")
    reply = soap_call(client, "ValidateToken", {"token": token})
    assert reply.number("user_id") == 1 and reply.text("email") == "val@example.com"


def test_validate_token_identifies_the_right_user(client):
    register(client, "one@example.com")
    t2 = register(client, "two@example.com").text("token")
    assert soap_call(client, "ValidateToken", {"token": t2}).text("email") == "two@example.com"


def test_validate_rejects_unknown_empty_and_missing_tokens(client):
    assert soap_call(client, "ValidateToken", {"token": "bogus"}).fault_code == "Client.Unauthorized"
    assert soap_call(client, "ValidateToken", {"token": "  "}).fault_code == "Client.Unauthorized"
    assert soap_call(client, "ValidateToken", {}).fault_code == "Client.Unauthorized"
