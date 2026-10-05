from models import Call, CallStatus, Conversation, Order, db
from tests.conftest import login


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


def test_orders_status_filter_lists_real_statuses(client, app):
    call = make_calls(1)[0]
    db.session.add_all([
        Order(call_id=call.id, order_number="1", status="Found in AfterBuy"),
        Order(call_id=call.id, order_number="2", status="Not Found"),
    ])
    db.session.commit()
    login(client, "operator")
    html = client.get("/orders").get_data(as_text=True)
    status_filter = html[html.index('<select class="form-select" id="status"'):]
    status_filter = status_filter[:status_filter.index("</select>")]
    assert 'value="Found in AfterBuy"' in status_filter
    assert 'value="Not Found"' in status_filter
    assert "Shipped" not in status_filter  # only statuses that exist


def test_order_detail_page(client, app):
    call = make_calls(1)[0]
    order = Order(call_id=call.id, order_number="24896241", status="Not Found", notes="line 1\nline 2")
    db.session.add(order)
    db.session.commit()
    login(client, "operator")
    html = client.get(f"/orders/{order.id}").get_data(as_text=True)
    assert "Order 24896241" in html
    assert "line 1\nline 2" in html
    assert 'id="orderStatusModal"' in html


def test_users_page_for_admin(client, app):
    login(client, "admin")
    html = client.get("/users").get_data(as_text=True)
    assert "Add user" in html and "(you)" in html
