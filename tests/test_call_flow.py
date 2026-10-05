import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import call_flow
import order_status as status
from models import Call, CallStatus, Conversation, Order, db
from tests.conftest import post_webhook

CALLER = "+4915112345678"
CALL_SID = "CAflow"
TWILIO_NUMBER = "+4973929169990"


def order(days_ago=20, phone="0151 12345678", postal="89073", paid="500,00", full="1.680,50"):
    return {
        "order_id": "24896241",
        "order_date": (date.today() - timedelta(days=days_ago)).strftime("%d.%m.%Y 10:00:00"),
        "payment": {"already_paid": paid, "full_amount": full},
        "buyer": {"first_name": "Max", "phone": phone, "postal_code": postal, "country": "DE"},
    }


@pytest.fixture
def call(app):
    call = Call(call_sid=CALL_SID, phone_number=CALLER, language="de")
    db.session.add(call)
    db.session.commit()
    return call


@pytest.fixture
def afterbuy(monkeypatch):
    orders = {}
    monkeypatch.setattr(call_flow, "get_order_from_afterbuy", lambda number: orders.get(number))
    return orders


@pytest.fixture
def open_hours(monkeypatch):
    monkeypatch.setattr(call_flow, "is_business_hours", lambda now=None: True)


@pytest.fixture
def closed_hours(monkeypatch):
    monkeypatch.setattr(call_flow, "is_business_hours", lambda now=None: False)


def hook(client, path, digits=None, **extra):
    params = {"From": CALLER, "To": TWILIO_NUMBER, "CallSid": CALL_SID, **extra}
    if digits is not None:
        params["Digits"] = digits
    resp = post_webhook(client, path, params)
    assert resp.status_code == 200
    return ET.fromstring(resp.get_data())


def text(root):
    return " ".join((s.text or "") for s in root.iter("Say"))


def gather_action(root):
    return root.find("Gather").get("action")


def events(step):
    return [c for c in Conversation.query.filter_by(step=step).all()]


# --- Greeting and main menu ----------------------------------------------------

def test_greeting_then_menu(client, app):
    root = hook(client, "/webhook/voice")
    assert "Lisa" in text(root)
    assert "Für den Status Ihrer Bestellung drücken Sie die Eins" in text(root)
    assert gather_action(root) == "/webhook/menu?attempt=1"
    # silence falls through to the same handler
    assert root.find("Redirect").text == "/webhook/menu?attempt=1"
    assert "Sind Sie damit einverstanden" not in text(root)


def test_menu_1_asks_for_order_number(client, call):
    root = hook(client, "/webhook/menu?attempt=1", "1")
    assert root.find("Gather").get("finishOnKey") == "#"
    assert gather_action(root) == "/webhook/order-number?attempt=1"


def test_menu_silence_repeats_once_then_goes_to_team(client, call, open_hours):
    root = hook(client, "/webhook/menu?attempt=1")
    assert gather_action(root) == "/webhook/menu?attempt=2"
    assert "nicht verstanden" not in text(root)  # silence: just repeat

    root = hook(client, "/webhook/menu?attempt=2")
    assert root.find("Dial") is not None


def test_menu_invalid_choice(client, call):
    root = hook(client, "/webhook/menu?attempt=1", "7")
    assert "nicht verstanden" in text(root)
    assert gather_action(root) == "/webhook/menu?attempt=2"


def test_menu_9_switches_to_english(client, call):
    root = hook(client, "/webhook/menu?attempt=1", "9")
    assert "For the status of your order" in text(root)
    says = list(root.iter("Say"))
    assert {s.get("language") for s in says[:-1]} == {"en-US"}
    assert says[-1].text == "Für Deutsch drücken Sie die Neun."  # offer back, in German
    assert says[-1].get("language") == "de-DE"
    db.session.refresh(call)
    assert call.language == "en"


def test_menu_2_records_voicemail(client, call):
    root = hook(client, "/webhook/menu?attempt=1", "2")
    record = root.find("Record")
    assert record.get("maxLength") == "120"
    assert record.get("action") == "/webhook/recorded"
    assert record.get("finishOnKey") == "#"
    assert events("voicemail_started")


# --- Team transfer -------------------------------------------------------------

def test_menu_0_dials_team_in_business_hours(client, call, open_hours):
    root = hook(client, "/webhook/menu?attempt=1", "0")
    dial = root.find("Dial")
    assert dial.get("callerId") == TWILIO_NUMBER
    assert dial.get("timeout") == "25"
    assert dial.get("action") == "/webhook/agent-result"
    assert [n.text for n in dial.iter("Number")] == ["+4973929378421"]


def test_menu_0_after_hours_offers_voicemail(client, call, closed_hours):
    root = hook(client, "/webhook/menu?attempt=1", "0")
    assert root.find("Dial") is None
    assert "montags bis freitags" in text(root)
    assert root.find("Record") is not None


def test_team_did_not_answer_offers_voicemail(client, call):
    root = hook(client, "/webhook/agent-result", DialCallStatus="no-answer")
    assert "niemand erreichbar" in text(root)
    assert root.find("Record") is not None


def test_team_answered_ends_call(client, call):
    root = hook(client, "/webhook/agent-result", DialCallStatus="completed")
    assert root.find("Hangup") is not None
    assert events("agent_connected")


# --- Order status ----------------------------------------------------------------

def test_found_and_verified_by_phone(client, call, afterbuy):
    afterbuy["24896241"] = order()
    root = hook(client, "/webhook/order-number?attempt=1", "24896241#")
    spoken = text(root)
    assert "Ihr Auftrag zwei vier acht neun sechs zwei vier eins ist in Produktion" in spoken
    assert "voraussichtlich zwischen dem" in spoken
    assert "Offen ist noch ein Betrag von 1180 Euro und 50 Cent" in spoken
    assert "Max" not in spoken  # no names on the phone
    assert gather_action(root).startswith("/webhook/next?")
    assert "verified=1" in gather_action(root)
    saved = Order.query.one()
    assert (saved.lookup_result, saved.verification) == ("found", "phone")
    assert saved.notes is None and saved.status is None  # staff fields stay empty
    db.session.refresh(call)
    assert call.status == CallStatus.COMPLETED


def test_no_open_amount_is_not_mentioned(client, call, afterbuy):
    afterbuy["1"] = order(paid="1.680,50")
    assert "Offen" not in text(hook(client, "/webhook/order-number?attempt=1", "1"))


def test_other_phone_asks_for_postal_code(client, call, afterbuy):
    afterbuy["555"] = order(phone="+49 30 9999999")
    root = hook(client, "/webhook/order-number?attempt=1", "555")
    assert "Postleitzahl" in text(root)
    assert gather_action(root) == "/webhook/plz?order=555&attempt=1"

    root = hook(client, "/webhook/plz?order=555&attempt=1", "89073")
    assert "in Produktion" in text(root)
    assert "Offen ist noch" in text(root)


def test_wrong_postal_code_twice_gives_no_details(client, call, afterbuy):
    afterbuy["555"] = order(phone="+49 30 9999999")
    root = hook(client, "/webhook/plz?order=555&attempt=1", "11111")
    assert "stimmt leider nicht" in text(root)
    assert gather_action(root) == "/webhook/plz?order=555&attempt=2"

    root = hook(client, "/webhook/plz?order=555&attempt=2", "11111")
    spoken = text(root)
    assert "Aus Datenschutzgründen" in spoken
    assert "Euro" not in spoken and "zwischen dem" not in spoken
    assert "verified=0" in gather_action(root)


def test_order_without_phone_or_postal_code_is_unverified(client, call, afterbuy):
    afterbuy["9"] = order(phone=None, postal=None)
    assert "Aus Datenschutzgründen" in text(hook(client, "/webhook/order-number?attempt=1", "9"))


def test_delivery_soon(client, call, afterbuy):
    _, max_weeks = status.production_weeks()
    afterbuy["7"] = order(days_ago=7 * (max_weeks + 2))  # window starts in about a week
    assert "fertig für die Auslieferung" in text(hook(client, "/webhook/order-number?attempt=1", "7"))


def test_overdue_goes_to_team(client, call, afterbuy, open_hours):
    afterbuy["8"] = order(days_ago=400)
    root = hook(client, "/webhook/order-number?attempt=1", "8")
    assert "verzögert sich leider" in text(root)
    assert root.find("Dial") is not None
    db.session.refresh(call)
    assert call.status == CallStatus.PROBLEM


def test_not_found_retry_then_options(client, call, afterbuy):
    root = hook(client, "/webhook/order-number?attempt=1", "123")
    assert "keinen Auftrag gefunden" in text(root)
    assert "Nummer eins zwei drei habe" in text(root)
    assert gather_action(root) == "/webhook/order-number?attempt=2"

    root = hook(client, "/webhook/order-number?attempt=2", "123")
    assert "wieder keinen Auftrag" in text(root)
    assert "Für einen neuen Versuch drücken Sie die Eins" in text(root)
    assert "kind=not_found" in gather_action(root)
    assert Order.query.filter_by(lookup_result="not_found").count() == 2


def test_order_number_silence_twice_goes_to_team(client, call, open_hours):
    root = hook(client, "/webhook/order-number?attempt=1")
    assert gather_action(root) == "/webhook/order-number?attempt=2"
    root = hook(client, "/webhook/order-number?attempt=2")
    assert root.find("Dial") is not None


# --- Follow-up menu ----------------------------------------------------------------

def test_star_repeats_status(client, call, afterbuy):
    afterbuy["24896241"] = order()
    root = hook(client, "/webhook/next?order=24896241&verified=1&kind=status&attempt=1", "*")
    assert "ist in Produktion" in text(root)


def test_next_1_new_order_and_silence_says_goodbye(client, call):
    root = hook(client, "/webhook/next?order=1&verified=1&kind=status&attempt=1", "1")
    assert gather_action(root) == "/webhook/order-number?attempt=1"

    root = hook(client, "/webhook/next?order=1&verified=1&kind=status&attempt=2")
    assert "Auf Wiederhören" in text(root)
    assert root.find("Hangup") is not None


# --- Safety --------------------------------------------------------------------

def test_tampered_state_in_url_is_rejected(client, call):
    from tests.conftest import TEST_ENV
    from twilio.request_validator import RequestValidator

    params = {"From": CALLER, "CallSid": CALL_SID, "Digits": "11111"}
    signed_url = "http://localhost/webhook/plz?order=555&attempt=1"
    signature = RequestValidator(TEST_ENV["TWILIO_AUTH_TOKEN"]).compute_signature(signed_url, params)
    resp = client.post(
        "/webhook/plz?order=555&verified=1&attempt=1",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )
    assert resp.status_code == 403


def test_crash_ends_call_politely(client, call, monkeypatch):
    def boom(number):
        raise RuntimeError("afterbuy exploded")

    monkeypatch.setattr(call_flow, "get_order_from_afterbuy", boom)
    root = hook(client, "/webhook/order-number?attempt=1", "1")
    assert "technischer Fehler" in text(root)
    assert root.find("Hangup") is not None


# --- Business hours & order_status units ------------------------------------------

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    "moment,expected",
    [
        (datetime(2026, 10, 5, 10, 0, tzinfo=BERLIN), True),   # Monday
        (datetime(2026, 10, 5, 7, 59, tzinfo=BERLIN), False),
        (datetime(2026, 10, 5, 17, 0, tzinfo=BERLIN), False),
        (datetime(2026, 10, 10, 10, 0, tzinfo=BERLIN), False),  # Saturday
    ],
)
def test_is_business_hours(moment, expected):
    assert call_flow.is_business_hours(moment) is expected


@pytest.mark.parametrize(
    "caller,stored,expected",
    [
        ("+4915112345678", "0151 12345678", True),
        ("+4915112345678", "+49 (151) 123-456-78", True),
        ("+4915112345678", "+49 151 99999999", False),
        ("+4915112345678", None, False),
        ("", "0151 12345678", False),
    ],
)
def test_phone_matches(caller, stored, expected):
    assert status.phone_matches(caller, stored) is expected


def test_postal_code_matches():
    assert status.postal_code_matches("89073", "89073")
    assert status.postal_code_matches("89073#", " 89073 ")
    assert not status.postal_code_matches("89074", "89073")
    assert not status.postal_code_matches("", None)


def test_delivery_stage_boundaries():
    window = (date(2026, 12, 29), date(2027, 1, 4))
    assert status.delivery_stage(window, date(2026, 12, 1)) == status.STAGE_PRODUCTION
    assert status.delivery_stage(window, date(2026, 12, 22)) == status.STAGE_DELIVERY_SOON
    assert status.delivery_stage(window, date(2027, 1, 4)) == status.STAGE_DELIVERY_SOON
    assert status.delivery_stage(window, date(2027, 1, 5)) == status.STAGE_OVERDUE


def test_speech_formatting():
    assert status.date_for_speech(date(2026, 12, 29), "de") == "29. Dezember"
    assert status.date_for_speech(date(2027, 1, 4), "en") == "January 4"
    assert status.euro_for_speech(1680.5, "de") == "1680 Euro und 50 Cent"
    assert status.euro_for_speech(500.0, "de") == "500 Euro"
    assert status.euro_for_speech(19.99, "en") == "19 euros and 99 cents"
    assert status.number_for_speech("248") == "zwei vier acht"
    assert status.number_for_speech("1090", "de") == "eins null neun null"
    assert status.number_for_speech("248", "en") == "2 4 8"


@pytest.mark.parametrize(
    "raw,expected",
    [("1680,50", 1680.5), ("1.680,50", 1680.5), ("1680.50", 1680.5), ("0,00", 0.0), ("", None), ("abc", None)],
)
def test_parse_amount(raw, expected):
    assert status.parse_amount(raw) == expected


def test_open_amount():
    assert status.open_amount(order(paid="500,00", full="1.680,50")) == 1180.5
    assert status.open_amount(order(paid="2.000,00", full="1.680,50")) == 0.0
    assert status.open_amount({"payment": {}}) == 0.0


def test_dashboard_funnel(client, call, afterbuy, open_hours):
    from analytics import funnel_stats
    from tests.conftest import login

    afterbuy["24896241"] = order()
    # A pre-v2 call (old step names) must not be counted
    legacy = Call(call_sid="CAlegacy", phone_number="+491", language="de")
    db.session.add(legacy)
    db.session.commit()
    db.session.add(Conversation(call_id=legacy.id, step="greeting"))
    db.session.commit()

    hook(client, "/webhook/voice")
    hook(client, "/webhook/menu?attempt=1", "1")
    hook(client, "/webhook/order-number?attempt=1", "24896241")
    stats = funnel_stats()
    assert stats["left_in_menu"] == 0
    assert stats["total"] == 1
    assert stats["status_spoken"] == 1
    assert stats["self_service"] == 1

    hook(client, "/webhook/next?order=24896241&verified=1&kind=status&attempt=1", "0")
    stats = funnel_stats()
    assert stats["agent_requested"] == 1
    assert stats["self_service"] == 0

    login(client, "operator")
    html = client.get("/").get_data(as_text=True)
    assert "Call journey" in html and "Solved without staff" in html and "Status shared" in html


def test_dashboard_renders_outcomes_and_chart(client, call, afterbuy):
    from tests.conftest import login

    afterbuy["24896241"] = order()
    hook(client, "/webhook/voice")
    hook(client, "/webhook/menu?attempt=1", "1")
    hook(client, "/webhook/order-number?attempt=1", "24896241")
    login(client, "operator")
    html = client.get("/").get_data(as_text=True)
    assert "Status shared" in html  # outcome badge of the call
    assert "Calls per day" in html and "<caption>Calls per day" in html
    assert 'aria-current="page"' in html  # Overview is active in the sidebar


def test_empty_dashboard(client, app):
    from tests.conftest import login

    login(client, "operator")
    html = client.get("/").get_data(as_text=True)
    assert "No calls yet" in html
    assert "—" in html  # no self-service rate without calls


# --- Event clarity ------------------------------------------------------------------

def steps_of(call):
    return [(c.step, c.user_input) for c in Conversation.query.filter_by(call_id=call.id).order_by(Conversation.id)]


def test_postcode_attempts_are_logged_and_order_marked(client, call, afterbuy):
    afterbuy["555"] = order(phone="+49 30 9999999")
    hook(client, "/webhook/order-number?attempt=1", "555")
    hook(client, "/webhook/plz?order=555&attempt=1", "11111")
    hook(client, "/webhook/plz?order=555&attempt=2")  # silence on the 2nd try
    steps = steps_of(call)
    assert ("ivr_plz_requested", "555 attempt=1") in steps
    assert ("ivr_plz_requested", "555 attempt=2") in steps
    assert ("ivr_plz_mismatch", "555 attempt=1") in steps
    assert ("ivr_plz_mismatch", "555 attempt=2 no_input") in steps
    assert ("status_spoken", "unverified") in steps
    assert Order.query.one().verification == "failed"
    assert Order.query.one().notes is None
    # the wrong postcode itself is never stored
    assert not any("11111" in (value or "") for _, value in steps)


def test_silence_and_transfer_reason_are_logged(client, call, open_hours):
    hook(client, "/webhook/order-number?attempt=1")
    hook(client, "/webhook/order-number?attempt=2")
    steps = steps_of(call)
    assert ("ivr_no_input", "order_number attempt=1") in steps
    assert ("ivr_no_input", "order_number attempt=2") in steps
    assert ("agent_requested", "no_input") in steps


def test_follow_up_choice_has_its_own_event(client, call):
    hook(client, "/webhook/next?order=1&verified=1&kind=status&attempt=1", "1")
    assert ("ivr_next_choice", "1") in steps_of(call)


@pytest.mark.parametrize(
    "step,value,expected",
    [
        ("menu_choice", "1", "Pressed 1 · order status"),
        ("menu_choice", "next:1", "Pressed 1 · another order"),  # legacy format on prod
        ("ivr_next_choice", "*", "Pressed * · repeat the status"),
        ("not_verified", "postal_code_mismatch", "Postcode didn't match twice · no details shared"),
        ("status_spoken", "830859702 verified=0", "Shared without details (caller not verified)"),  # legacy
        ("status_spoken", "verified", "Shared delivery window and open balance"),
        ("ivr_no_input", "order_number attempt=2", "Nothing entered in the order number · attempt 2 of 2"),
        ("ivr_plz_mismatch", "555 attempt=1", "Order 555 · attempt 1 of 2"),
        ("agent_requested", "no_input", "No input from the caller"),
        ("agent_connected", "completed", "Call answered"),
    ],
)
def test_event_detail_is_human_readable(step, value, expected):
    from ui import event_detail

    assert event_detail(step, value)[0] == expected


def test_order_numbers_stay_monospace():
    from ui import event_detail

    assert event_detail("ivr_order_number", "24896241") == ("24896241", True)


def test_verification_card_flags_probing(client, app, afterbuy):
    from analytics import verification_failures
    from tests.conftest import login

    afterbuy["555"] = order(phone="+49 30 9999999")
    for i in range(2):  # two calls, 2 wrong postcodes each
        params = {"From": CALLER, "To": TWILIO_NUMBER, "CallSid": f"CAprobe{i}"}
        post_webhook(client, "/webhook/voice", params)
        post_webhook(client, "/webhook/plz?order=555&attempt=1", {**params, "Digits": "11111"})
        post_webhook(client, "/webhook/plz?order=555&attempt=2", {**params, "Digits": "22222"})

    v = verification_failures()
    assert v["orders"][0]["number"] == "555"
    assert v["orders"][0]["attempts"] == 4 and v["orders"][0]["calls"] == 2
    assert v["suspicious"] == 1

    login(client, "operator")
    html = client.get("/").get_data(as_text=True)
    assert "Possible probing" in html


def test_call_detail_shows_readable_events(client, call, afterbuy):
    from tests.conftest import login

    afterbuy["555"] = order(phone="+49 30 9999999")
    hook(client, "/webhook/order-number?attempt=1", "555")
    hook(client, "/webhook/plz?order=555&attempt=1", "1")
    login(client, "operator")
    html = client.get(f"/calls/{call.id}").get_data(as_text=True)
    assert "Postcode requested" in html and "Postcode didn&#39;t match" in html
    assert "attempt 1 of 2" in html
    assert "attempt=1" not in html
