from models import Call, CallStatus, Conversation, Order, db
from tests.conftest import get_csrf_token, login


def make_calls(n, **fields):
    calls = []
    for i in range(n):
        call = Call(call_sid=f"CA{i}", phone_number=f"+4917600000{i:03d}", language="de", **fields)
        db.session.add(call)
        calls.append(call)
    db.session.commit()
    return calls


def test_calls_page_filters_survive_pagination(client, app):
    make_calls(25, status=CallStatus.COMPLETED)
    login(client, "operator")
    html = client.get("/calls?status=COMPLETED").get_data(as_text=True)
    assert "Page 1 of 2" in html
    assert "/calls?status=COMPLETED&amp;page=2" in html


def test_calls_page_empty_states(client, app):
    login(client, "operator")
    assert "No calls yet" in client.get("/calls").get_data(as_text=True)
    filtered = client.get("/calls?phone=999").get_data(as_text=True)
    assert "No calls match these filters" in filtered and "Reset filters" in filtered


def test_call_detail_timeline_uses_readable_labels(client, app):
    call = make_calls(1)[0]
    db.session.add(Conversation(call_id=call.id, step="ivr_order_number", user_input="24896241"))
    db.session.commit()
    login(client, "operator")
    html = client.get(f"/calls/{call.id}").get_data(as_text=True)
    assert "Order number entered" in html
    assert "24896241" in html
    assert 'aria-current="page"' in html  # Calls stays highlighted in the sidebar


def test_orders_result_filter(client, app):
    from datetime import date, timedelta

    call = make_calls(1)[0]
    db.session.add_all([
        Order(call_id=call.id, order_number="111", lookup_result="found", verification="phone",
              promised_delivery_date=date.today() + timedelta(days=30)),
        Order(call_id=call.id, order_number="222", lookup_result="not_found"),
        Order(call_id=call.id, order_number="333", lookup_result="found", verification="failed",
              promised_delivery_date=date.today() - timedelta(days=3)),
        Order(call_id=call.id, order_number="444", lookup_result="found", status="Delivered",
              promised_delivery_date=date.today() - timedelta(days=3)),
    ])
    db.session.commit()
    login(client, "operator")

    def numbers(query):
        html = client.get("/orders" + query).get_data(as_text=True)
        return [n for n in ("111", "222", "333", "444") if f"<strong>{n}</strong>" in html]

    assert numbers("?result=not_found") == ["222"]
    assert numbers("?result=verification_failed") == ["333"]
    assert numbers("?result=overdue") == ["333"]  # delivered orders are not overdue
    assert len(numbers("")) == 4


def test_order_detail_shows_afterbuy_data(client, app, monkeypatch):
    import app as app_module

    call = make_calls(1)[0]
    order = Order(call_id=call.id, order_number="24896241", lookup_result="found", verification="failed",
                  notes="Customer asked for a callback")
    db.session.add(order)
    db.session.commit()
    monkeypatch.setattr(app_module, "get_order_from_afterbuy", lambda n: {
        "order_id": n, "invoice_number": "RE-1", "order_date": "18.09.2026 10:00:00",
        "buyer": {"first_name": "Max", "last_name": "Muster", "phone": "0151 2222222",
                  "postal_code": "89073", "city": "Ulm", "country": "DE"},
        "payment": {"full_amount": "1.680,50", "already_paid": "500,00"},
    })
    login(client, "operator")
    html = client.get(f"/orders/{order.id}").get_data(as_text=True)
    assert "Max Muster" in html and "89073 Ulm" in html
    assert "1.680,50 €" in html and "1.180,50 €" in html
    assert "Postcode didn&#39;t match twice" in html
    assert "The caller used +4917600000000" in html
    assert "Lisa's estimate" in html
    assert "Customer asked for a callback" in html


def test_order_detail_when_afterbuy_is_down(client, app, monkeypatch):
    import app as app_module

    call = make_calls(1)[0]
    order = Order(call_id=call.id, order_number="1", lookup_result="found")
    db.session.add(order)
    db.session.commit()

    def down(number):
        raise ConnectionError("afterbuy down")

    monkeypatch.setattr(app_module, "get_order_from_afterbuy", down)
    login(client, "operator")
    resp = client.get(f"/orders/{order.id}")
    assert resp.status_code == 200
    assert "Couldn&#39;t load this order from Afterbuy" in resp.get_data(as_text=True)


def test_not_found_order_skips_afterbuy(client, app, monkeypatch):
    import app as app_module

    call = make_calls(1)[0]
    order = Order(call_id=call.id, order_number="9", lookup_result="not_found")
    db.session.add(order)
    db.session.commit()
    monkeypatch.setattr(app_module, "get_order_from_afterbuy", lambda n: (_ for _ in ()).throw(AssertionError))
    login(client, "operator")
    html = client.get(f"/orders/{order.id}").get_data(as_text=True)
    assert "Not found" in html and "Afterbuy</h2>" not in html


def test_money_format():
    from ui import money

    assert money(1680.5) == "1.680,50 €"
    assert money(0) == "0,00 €"
    assert money(None) == "—"


def test_migration_moves_system_data_out_of_staff_fields(tmp_path):
    """Old rows: system status/notes -> lookup_result/verification, notes cleaned"""
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine, text

    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    env = {**os.environ, "DATABASE_URL": db_url}

    def flask_db(*args):
        result = subprocess.run([sys.executable, "-m", "flask", "--app", "app", "db", *args],
                                cwd=project, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    flask_db("upgrade", "8188b5c6049d")
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO calls (id, call_sid, phone_number, language, status, created_at, updated_at) "
                          "VALUES (1, 'CA1', '+491', 'de', 'COMPLETED', '2026-10-05', '2026-10-05')"))
        conn.execute(text("INSERT INTO conversations (call_id, step, user_input, timestamp) VALUES "
                          "(1, 'not_verified', 'postal_code_mismatch', '2026-10-05')"))
        conn.execute(text("INSERT INTO orders (id, call_id, order_number, status, notes, created_at, updated_at) VALUES "
                          "(1, 1, '830859702', 'Found in AfterBuy', 'Verification: postal_code_requested', '2026-10-05', '2026-10-05'), "
                          "(2, 1, '123', 'Not Found', 'Order not found in AfterBuy system', '2026-10-05', '2026-10-05'), "
                          "(3, 1, '777', 'Shipped', 'Called back\nVoice message (12s): https://x', '2026-10-05', '2026-10-05')"))
    flask_db("upgrade")
    with engine.connect() as conn:
        rows = {r[0]: r[1:] for r in conn.execute(text(
            "SELECT id, lookup_result, verification, status, notes FROM orders"))}
    assert rows[1] == ("found", "failed", None, None)       # verification taken from the call's events
    assert rows[2] == ("not_found", None, None, None)
    assert rows[3] == (None, None, "Shipped", "Called back")  # staff data kept, system line removed


def test_users_page_for_admin(client, app):
    login(client, "admin")
    html = client.get("/users").get_data(as_text=True)
    assert "Add user" in html and "(you)" in html


def test_detail_pages_have_back_link(client, app):
    call = make_calls(1)[0]
    order = Order(call_id=call.id, order_number="1", lookup_result="not_found")
    db.session.add(order)
    db.session.commit()
    login(client, "operator")
    call_html = client.get(f"/calls/{call.id}").get_data(as_text=True)
    order_html = client.get(f"/orders/{order.id}").get_data(as_text=True)
    assert 'href="/calls" data-back' in call_html and "Back to calls" in call_html
    assert 'href="/orders" data-back' in order_html and "Back to orders" in order_html


def test_styled_error_pages(client, app):
    login(client, "operator")
    resp = client.get("/calls/999999")
    assert resp.status_code == 404
    html = resp.get_data(as_text=True)
    assert "Page not found" in html and 'class="sidebar"' in html
    resp = client.get("/users")
    assert resp.status_code == 403 and "only available to admins" in resp.get_data(as_text=True)
    resp = client.post("/api/calls/999999/status", json={"status": "COMPLETED"},
                       headers={"X-CSRFToken": get_csrf_token(client, "/calls")})
    assert resp.status_code == 404 and resp.is_json


def test_tables_are_marked_for_mobile_cards(client, app):
    call = make_calls(1)[0]
    db.session.add(Order(call_id=call.id, order_number="1", lookup_result="not_found"))
    db.session.commit()
    login(client, "admin")
    for path in ("/calls", "/orders", "/users"):
        html = client.get(path).get_data(as_text=True)
        assert "table-c table-stack" in html, path
        assert 'data-label="' in html and "cell-primary" in html, path
    assert "data-filters" in client.get("/calls").get_data(as_text=True)
