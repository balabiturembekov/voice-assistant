import logging

from twilio.request_validator import RequestValidator

from models import Call, CallStatus, db
from security import PIIMaskingFilter
from tests.conftest import get_csrf_token, login

CALL_PARAMS = {"From": "+4915112345678", "CallSid": "CAtest123"}


def signed_headers(url, params, token="test-twilio-token"):
    signature = RequestValidator(token).compute_signature(url, params)
    return {"X-Twilio-Signature": signature}


# --- Twilio webhooks ---------------------------------------------------------

def test_webhook_without_signature_is_rejected(client):
    assert client.post("/webhook/voice", data=CALL_PARAMS).status_code == 403


def test_webhook_with_wrong_signature_is_rejected(client):
    headers = signed_headers("http://localhost/webhook/voice", CALL_PARAMS, token="other")
    resp = client.post("/webhook/voice", data=CALL_PARAMS, headers=headers)
    assert resp.status_code == 403


def test_webhook_with_valid_signature_is_accepted(client):
    headers = signed_headers("http://localhost/webhook/voice", CALL_PARAMS)
    resp = client.post("/webhook/voice", data=CALL_PARAMS, headers=headers)
    assert resp.status_code == 200
    assert b"<Gather" in resp.data


def test_webhook_signature_uses_https_url_behind_proxy(client):
    url = "https://lisa.automatonsoft.de/webhook/voice"
    headers = signed_headers(url, CALL_PARAMS)
    headers.update({"X-Forwarded-Proto": "https", "Host": "lisa.automatonsoft.de"})
    resp = client.post("/webhook/voice", data=CALL_PARAMS, headers=headers)
    assert resp.status_code == 200


# --- Dashboard login ---------------------------------------------------------

def test_dashboard_requires_login(client):
    resp = client.get("/calls")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_requires_login(client):
    assert client.get("/api/health").status_code == 401


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_test_email_endpoint_removed(client):
    login(client, "admin")
    assert client.get("/api/test-email").status_code == 404


def test_login_with_wrong_password_fails(client):
    resp = login(client, "admin", "wrong-password")
    assert resp.status_code == 200
    assert client.get("/calls").status_code == 302


def test_login_and_logout(client):
    resp = login(client, "operator")
    assert resp.status_code == 302
    assert client.get("/calls").status_code == 200

    token = get_csrf_token(client, "/calls")
    client.post("/logout", data={"csrf_token": token})
    assert client.get("/calls").status_code == 302


def test_login_rejects_open_redirect(client):
    token = get_csrf_token(client)
    resp = client.post(
        "/login?next=https://evil.example/",
        data={"username": "admin", "password": "correct-horse-battery", "csrf_token": token},
    )
    assert resp.headers["Location"] == "/"


def test_login_without_csrf_token_fails(client):
    resp = client.post("/login", data={"username": "admin", "password": "x"})
    assert resp.status_code == 400


def test_disabled_user_cannot_login(app, client):
    from models import User

    user = User.query.filter_by(username="operator").first()
    user.is_active_user = False
    db.session.commit()
    login(client, "operator")
    assert client.get("/calls").status_code == 302


# --- CSRF on the JSON API ----------------------------------------------------

def _make_call():
    call = Call(call_sid="CAapi", phone_number="+491234567", language="de")
    db.session.add(call)
    db.session.commit()
    return call.id


def test_api_status_update_needs_csrf_token(app, client):
    call_id = _make_call()
    login(client, "operator")
    resp = client.post(f"/api/calls/{call_id}/status", json={"status": "HANDLED"})
    assert resp.status_code == 400


def test_api_status_update_with_csrf_token(app, client):
    call_id = _make_call()
    login(client, "operator")
    token = get_csrf_token(client, "/calls")
    resp = client.post(
        f"/api/calls/{call_id}/status",
        json={"status": "HANDLED"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
    assert db.session.get(Call, call_id).status == CallStatus.HANDLED


# --- Roles -------------------------------------------------------------------

def test_operator_cannot_manage_users(client):
    login(client, "operator")
    assert client.get("/users").status_code == 403


def test_admin_can_create_user(client):
    login(client, "admin")
    token = get_csrf_token(client, "/users")
    resp = client.post(
        "/users",
        data={"username": "new", "password": "long-enough-pass", "role": "OPERATOR", "csrf_token": token},
    )
    assert resp.status_code == 302
    from models import User

    assert User.query.filter_by(username="new").first() is not None


def test_admin_cannot_create_user_with_short_password(client):
    login(client, "admin")
    token = get_csrf_token(client, "/users")
    client.post("/users", data={"username": "x", "password": "short", "role": "OPERATOR", "csrf_token": token})
    from models import User

    assert User.query.filter_by(username="x").first() is None


# --- Logs --------------------------------------------------------------------

def test_phone_numbers_are_masked_in_logs():
    record = logging.LogRecord("t", logging.INFO, "", 0, "Call from %s", ("+4915112345678",), None)
    PIIMaskingFilter().filter(record)
    assert record.getMessage() == "Call from ***678"


def test_order_numbers_are_not_masked():
    record = logging.LogRecord("t", logging.INFO, "", 0, "Order 123456789 confirmed", (), None)
    PIIMaskingFilter().filter(record)
    assert record.getMessage() == "Order 123456789 confirmed"
