from datetime import date, timedelta

import pytest

import call_flow
import order_status as status
from afterbuy_client import AfterbuyClient
from models import Call, Order, db
from tests.conftest import login, post_webhook

CALLER = "+4915112345678"


def order(**extra):
    data = {
        "order_id": "24896241",
        "order_date": (date.today() - timedelta(days=20)).strftime("%d.%m.%Y 10:00:00"),
        "payment": {"already_paid": "500,00", "full_amount": "1.680,50"},
        "buyer": {"phone": "0151 12345678", "postal_code": "89073"},
    }
    data.update(extra)
    return data


def kw_ahead(weeks):
    return (date.today() + timedelta(weeks=weeks)).isocalendar()[1]


# --- Afterbuy XML -----------------------------------------------------------------

AFTERBUY_XML = """<?xml version="1.0"?><Afterbuy><CallStatus>Success</CallStatus><Result><Orders><Order>
<OrderID>1</OrderID><OrderDate>30.09.2026 06:46:48</OrderDate><Memo>30-09-2026 KW 44 - 45 0</Memo>
<PaymentInfo><PaymentMethod>TEMU</PaymentMethod><AlreadyPaid>0,00</AlreadyPaid><FullAmount>499,00</FullAmount></PaymentInfo>
<SoldItems><SoldItem><ItemTitle>Sofa</ItemTitle><ItemQuantity>1</ItemQuantity><ItemPrice>499,00</ItemPrice>
<ItemPlatformName>TEMU</ItemPlatformName><UserDefinedFlag>14203</UserDefinedFlag></SoldItem></SoldItems>
<ShippingInfo><DeliveryDate>12.10.2026 00:00:00</DeliveryDate><ShippingMethod>Spedition</ShippingMethod>
<ParcelLabels><ParcelLabel><ParcelLabelNumber>DHL123</ParcelLabelNumber></ParcelLabel></ParcelLabels></ShippingInfo>
</Order></Orders></Result></Afterbuy>"""


def test_afterbuy_parser_reads_delivery_and_marketplace_fields():
    data = AfterbuyClient("", "", "", "", "")._parse_order_response(AFTERBUY_XML)
    assert data["shipping"]["delivery_date"] == "12.10.2026 00:00:00"
    assert data["shipping"]["method"] == "Spedition"
    assert data["shipping"]["parcel_numbers"] == ["DHL123"]
    assert data["platform"] == "TEMU"
    assert data["payment"]["payment_method"] == "TEMU"
    assert data["items"][0]["user_flag"] == "14203"


# --- Delivery sources -------------------------------------------------------------

def test_shipped_date_wins():
    info = status.delivery_info(order(shipping={"delivery_date": "12.10.2026 00:00:00"}, memo="KW 1 - 2"))
    assert info == {"source": "shipped", "shipped_on": date(2026, 10, 12), "stage": None}


def test_memo_week_range_last_line_wins():
    data = order(order_date="30.09.2026", memo="30-09-2026 KW 44 - 45 123\n02-10-2026 KW 46 - 47 0")
    info = status.delivery_info(data, today=date(2026, 10, 5))
    assert info["source"] == "planned" and info["weeks"] == (46, 47)
    assert info["window"] == (date(2026, 11, 9), date(2026, 11, 22))
    assert info["stage"] == "production"


@pytest.mark.parametrize(
    "memo,weeks",
    [("Lieferung KW 45", (45, 45)), ("kw 3-4", (3, 4)), ("KW 51 - KW 2", (51, 2)), ("KW45/46", (45, 46))],
)
def test_memo_week_formats(memo, weeks):
    assert status.promised_weeks({"memo": memo}) == weeks


def test_week_window_rolls_over_the_year():
    assert status.week_window((2, 3), date(2026, 12, 20)) == (date(2027, 1, 11), date(2027, 1, 24))
    assert status.week_window((51, 2), date(2026, 12, 1)) == (date(2026, 12, 14), date(2027, 1, 17))


def test_invalid_week_falls_back_to_estimate():
    assert status.delivery_info(order(memo="KW 60 - 61"))["source"] == "estimated"
    assert status.delivery_info(order())["source"] == "estimated"
    assert status.delivery_info({"memo": "KW 45"}) is None  # no order date


def test_planned_window_in_the_past_is_overdue():
    data = order(memo=f"KW {kw_ahead(-4)} - {kw_ahead(-3)}")
    assert status.delivery_info(data)["stage"] == status.STAGE_OVERDUE


def test_marketplace_orders_have_no_open_amount():
    temu = order(payment={"payment_method": "TEMU", "already_paid": "0,00", "full_amount": "499,00"})
    otto = order(platform="Otto")
    assert status.is_marketplace(temu) and status.open_amount(temu) == 0
    assert status.is_marketplace(otto) and status.open_amount(otto) == 0
    assert not status.is_marketplace(order(platform="sellcreator"))
    assert status.open_amount(order(platform="sellcreator")) == 1180.5


# --- What Lisa says -----------------------------------------------------------------

@pytest.fixture
def call(app):
    call = Call(call_sid="CAdel", phone_number=CALLER, language="de")
    db.session.add(call)
    db.session.commit()
    return call


def say_status(client, monkeypatch, data):
    monkeypatch.setattr(call_flow, "get_order_from_afterbuy", lambda number: data)
    monkeypatch.setattr(call_flow, "is_business_hours", lambda now=None: True)
    resp = post_webhook(client, "/webhook/order-number?attempt=1",
                        {"From": CALLER, "To": "+491", "CallSid": "CAdel", "Digits": "24896241"})
    return resp.get_data(as_text=True)


def test_lisa_says_the_shipping_date(client, call, monkeypatch):
    xml = say_status(client, monkeypatch, order(shipping={"delivery_date": "12.10.2026"}))
    assert "wurde am 12. Oktober versendet" in xml
    assert "voraussichtlich" not in xml


def test_lisa_says_the_planned_week(client, call, monkeypatch):
    a, b = kw_ahead(4), kw_ahead(5)
    xml = say_status(client, monkeypatch, order(memo=f"01-01-2026 KW {a} - {b} 0"))
    assert f"in Kalenderwoche {a} bis {b} eingeplant" in xml
    assert "also zwischen dem" in xml


def test_overdue_planned_week_goes_to_team(client, call, monkeypatch):
    xml = say_status(client, monkeypatch, order(memo=f"KW {kw_ahead(-4)} - {kw_ahead(-3)}"))
    assert "verzögert sich leider" in xml and "<Dial" in xml


def test_lisa_does_not_mention_open_amount_for_marketplace_orders(client, call, monkeypatch):
    xml = say_status(client, monkeypatch, order(payment={"payment_method": "OTTO-Payments", "already_paid": "0,00",
                                                         "full_amount": "1.680,50"}))
    assert "Offen ist noch" not in xml


def test_saved_order_uses_the_planned_window_end(client, call, monkeypatch):
    a, b = kw_ahead(4), kw_ahead(5)
    say_status(client, monkeypatch, order(memo=f"KW {a} - {b}"))
    saved = Order.query.one()
    assert saved.promised_delivery_date.isocalendar()[1] == b
    assert saved.promised_delivery_date.weekday() == 6  # Sunday, end of week b


# --- Staff order page ------------------------------------------------------------------

def test_order_page_shows_afterbuy_details(client, app, monkeypatch):
    import app as app_module

    call = Call(call_sid="CApage", phone_number=CALLER, language="de")
    db.session.add(call)
    db.session.commit()
    saved = Order(call_id=call.id, order_number="1", lookup_result="found", verification="phone")
    db.session.add(saved)
    db.session.commit()
    data = AfterbuyClient("", "", "", "", "")._parse_order_response(AFTERBUY_XML)
    monkeypatch.setattr(app_module, "get_order_from_afterbuy", lambda n: data)
    login(client, "operator")
    html = client.get(f"/orders/{saved.id}").get_data(as_text=True)
    assert "Shipped on 12.10.2026" in html
    assert "Paid via marketplace" in html and "Lisa never mentions an open amount" in html
    assert "Sofa" in html and "Spedition" in html and "DHL123" in html
    assert "Afterbuy memo" in html and "KW 44 - 45" in html
