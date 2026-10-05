import xml.etree.ElementTree as ET

import pytest

import app as app_module
from config import Config
from models import Call, db
from tests.conftest import post_webhook


def says(resp):
    root = ET.fromstring(resp.get_data())
    return list(root.iter("Say"))


@pytest.mark.parametrize(
    "number,voice_attr,language_code",
    [("+4915112345678", "VOICE_DE", "de-DE"), ("+12025550123", "VOICE_EN", "en-US")],
)
def test_every_say_gets_voice_and_language(client, app, number, voice_attr, language_code):
    resp = post_webhook(client, "/webhook/voice", {"From": number, "CallSid": f"CA{number}"})
    elements = says(resp)
    assert len(elements) >= 2  # greeting + consent question (+ goodbye)
    for say in elements:
        assert say.get("voice") == getattr(Config, voice_attr)
        assert say.get("language") == language_code
        assert "voiceEngine" not in say.attrib


def test_follow_up_webhooks_use_call_language(client, app):
    db.session.add(Call(call_sid="CAen", phone_number="+12025550123", language="en"))
    db.session.commit()
    resp = post_webhook(client, "/webhook/consent", {"From": "+12025550123", "CallSid": "CAen", "Digits": "1"})
    assert {say.get("language") for say in says(resp)} == {"en-US"}


@pytest.mark.parametrize("digits", ["1", "2", "9"])
def test_prompts_never_contain_hash_symbol(client, app, digits):
    db.session.add(Call(call_sid="CAhash", phone_number="+4915112345678", language="de"))
    db.session.commit()
    for path in ("/webhook/consent", "/webhook/order_availability", "/webhook/voice_message"):
        resp = post_webhook(client, path, {"From": "+4915112345678", "CallSid": "CAhash", "Digits": digits})
        for say in says(resp):
            assert "#" not in (say.text or ""), say.text


def test_greeting_asks_for_consent(client, app):
    resp = post_webhook(client, "/webhook/voice", {"From": "+4915112345678", "CallSid": "CAgreet"})
    text = " ".join(say.text for say in says(resp))
    assert "Lisa" in text
    assert "einverstanden" in text


@pytest.mark.parametrize(
    "raw,expected",
    [("1680,50", 1680.5), ("1.680,50", 1680.5), ("1680.50", 1680.5), ("0,00", 0.0), ("", None), ("abc", None)],
)
def test_parse_amount(raw, expected):
    assert app_module.parse_amount(raw) == expected


def test_euro_for_speech():
    assert app_module.euro_for_speech(1680.5, "de") == "1680 Euro und 50 Cent"
    assert app_module.euro_for_speech(500.0, "de") == "500 Euro"
    assert app_module.euro_for_speech(19.99, "en") == "19 euros and 99 cents"


def test_status_speech_is_well_formed():
    order = {
        "order_id": "24896241",
        "order_date": "18.09.2026 16:27:55",
        "payment": {"already_paid": "500,00", "full_amount": "1.680,50"},
        "buyer": {"first_name": "", "country": "DE"},
    }
    text = app_module.format_order_status_for_speech(order, "de")
    assert "500 Euro bezahlt" in text
    assert "1680 Euro und 50 Cent" in text
    assert "/" not in text  # no 'Schrägstrich'
    assert "auf den Namen" not in text  # empty name is skipped
    assert "Kalenderwoche" in text
