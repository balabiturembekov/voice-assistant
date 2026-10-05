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
    assert len(elements) >= 3  # greeting + menu + language switch (+ goodbye)
    main, switch = elements[:-1], elements[-1]
    for say in elements:
        assert "voiceEngine" not in say.attrib
    for say in main:
        assert say.get("voice") == getattr(Config, voice_attr)
        assert say.get("language") == language_code
    # The language switch offer is spoken in the other language, with its voice
    other_voice, other_code = ("VOICE_EN", "en-US") if language_code == "de-DE" else ("VOICE_DE", "de-DE")
    assert switch.get("language") == other_code
    assert switch.get("voice") == getattr(Config, other_voice)


def test_german_prompts_say_numbers_as_words():
    """'die 1.' is read as an ordinal ('die erste'); prompts must say 'die Eins'"""
    import re

    from prompts import LANGUAGE_SWITCH, PROMPTS

    texts = list(PROMPTS["de"].values()) + [LANGUAGE_SWITCH["en"][1]]
    for text in texts:
        assert not re.search(r"\bdie \d", text), text
    assert "die Eins" in PROMPTS["de"]["menu"] and "die Null" in PROMPTS["de"]["menu"]


def test_follow_up_webhooks_use_call_language(client, app):
    db.session.add(Call(call_sid="CAen", phone_number="+12025550123", language="en"))
    db.session.commit()
    resp = post_webhook(client, "/webhook/menu?attempt=1", {"From": "+12025550123", "CallSid": "CAen", "Digits": "1"})
    assert {say.get("language") for say in says(resp)} == {"en-US"}


@pytest.mark.parametrize("digits", ["1", "2", "0", "7", ""])
def test_prompts_never_contain_hash_symbol(client, app, digits):
    db.session.add(Call(call_sid="CAhash", phone_number="+4915112345678", language="de"))
    db.session.commit()
    for path in ("/webhook/menu?attempt=1", "/webhook/next?attempt=1&kind=not_found"):
        resp = post_webhook(client, path, {"From": "+4915112345678", "CallSid": "CAhash", "Digits": digits})
        for say in says(resp):
            assert "#" not in (say.text or ""), say.text


def test_greeting_introduces_lisa_and_company(client, app):
    resp = post_webhook(client, "/webhook/voice", {"From": "+4915112345678", "CallSid": "CAgreet"})
    text = " ".join(say.text for say in says(resp))
    assert "Lisa" in text and Config.COMPANY_NAME in text
    assert "Datenschutz" in text
