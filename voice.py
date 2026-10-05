"""
Text-to-speech voice for every <Say>: one place decides voice and language,
so no prompt is ever read with the wrong (or default English) pronunciation.
"""
import logging
import xml.etree.ElementTree as ET

from flask import request

from config import Config
from models import Call
from services import detect_language

logger = logging.getLogger(__name__)

# Twilio language codes per call language
LANGUAGE_CODES = {"de": "de-DE", "en": "en-US"}


def voice_for(language):
    """(voice, language code) for a call language"""
    if language == "en":
        return Config.VOICE_EN, LANGUAGE_CODES["en"]
    return Config.VOICE_DE, LANGUAGE_CODES["de"]


def _call_language():
    call_sid = request.form.get("CallSid", "")
    if call_sid:
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call and call.language:
            return call.language
    return detect_language(request.form.get("From", ""))


def apply_voice(response):
    """after_request hook: set voice/language on all <Say> in webhook TwiML"""
    if not request.path.startswith("/webhook/") or response.mimetype != "text/xml":
        return response
    try:
        root = ET.fromstring(response.get_data())
        voice, language_code = voice_for(_call_language())
        for say in root.iter("Say"):
            say.set("voice", voice)
            say.set("language", language_code)
            # Not a TwiML attribute; older code passed it
            say.attrib.pop("voiceEngine", None)
        response.set_data(
            '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
        )
    except Exception as e:
        # Never break a live call because of voice styling
        logger.error(f"Could not apply voice to TwiML for {request.path}: {e}")
    return response
