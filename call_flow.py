"""
Call flow v2 (IVR): greeting -> main menu -> order status / voicemail / team.

Each step renders a <Gather> whose action is the step's input handler, followed by
a <Redirect> to the same handler, so silence arrives there without Digits.
Per-call state (order number, verification, attempt) travels in the action URL;
Twilio signs the full URL, so it can't be tampered with.
"""
import logging
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, request, url_for
from twilio.twiml.voice_response import VoiceResponse

import order_status as status
from calls import create_or_get_call, log_conversation, update_call_status
from config import Config
from models import Call, CallStatus, Order, db
from order_lookup import get_order_from_afterbuy
from prompts import prompt
from services import detect_language
from voice_messages import uses_external_transcription

logger = logging.getLogger(__name__)

flow_bp = Blueprint("flow", __name__)

MAX_ATTEMPTS = 2
MENU_TIMEOUT = 6
NUMBER_TIMEOUT = 10
VOICEMAIL_MAX_LENGTH = 120

# Conversation.step values; the dashboard funnel counts these
EVENT_GREETING = "greeting"
EVENT_MENU = "menu_choice"
EVENT_ORDER_INPUT = "order_input"
EVENT_ORDER_FOUND = "order_found"
EVENT_ORDER_NOT_FOUND = "order_not_found"
EVENT_VERIFIED = "verified"
EVENT_NOT_VERIFIED = "not_verified"
EVENT_STATUS = "status_spoken"
EVENT_OVERDUE = "status_overdue"
EVENT_AGENT_REQUESTED = "agent_requested"
EVENT_AFTER_HOURS = "agent_after_hours"
EVENT_AGENT_CONNECTED = "agent_connected"
EVENT_AGENT_NO_ANSWER = "agent_no_answer"
EVENT_VOICEMAIL = "voicemail_started"
EVENT_GOODBYE = "goodbye"


# --- Helpers -----------------------------------------------------------------

def twiml_route(rule):
    """Register a webhook that returns TwiML; any crash ends the call politely"""

    def decorator(handler):
        @wraps(handler)
        def wrapped():
            try:
                response = handler()
            except Exception:
                logger.exception(f"Call flow error in {rule}")
                db.session.rollback()
                response = VoiceResponse()
                call = _current_call()
                response.say(prompt(_language(call), "error"))
                response.hangup()
            return Response(str(response), mimetype="text/xml")

        return flow_bp.route(rule, methods=["POST"], endpoint=handler.__name__)(wrapped)

    return decorator


def _current_call():
    call_sid = request.form.get("CallSid", "")
    return Call.query.filter_by(call_sid=call_sid).first() if call_sid else None


def _language(call):
    if call and call.language:
        return call.language
    return detect_language(request.form.get("From", ""))


def _digits():
    return request.form.get("Digits", "").strip()


def _arg_int(name, default=1):
    try:
        return int(request.args.get(name, default))
    except ValueError:
        return default


def _say(verb, call, key, **values):
    """Say a prompt and record it in the call log"""
    text = prompt(_language(call), key, **values)
    verb.say(text)
    return text


def _event(call, step, user_input=None, bot_response=None):
    if call:
        log_conversation(call.id, step, user_input=user_input, bot_response=bot_response)


def _gather(response, endpoint, *, num_digits=None, finish_on_key="#", timeout=MENU_TIMEOUT, **params):
    """<Gather> posting to `endpoint`, then a <Redirect> there for silence"""
    action = url_for(f"flow.{endpoint}", **params)
    options = {"input": "dtmf", "action": action, "method": "POST", "timeout": timeout}
    if num_digits:
        options["num_digits"] = num_digits
    options["finish_on_key"] = finish_on_key
    gather = response.gather(**options)
    response.redirect(action, method="POST")
    return gather


def _now():
    return datetime.now(ZoneInfo(Config.TIMEZONE))


def _parse_days(spec):
    """'0-4' -> {0,1,2,3,4}; '0,2,4' -> {0,2,4}"""
    days = set()
    for part in spec.split(","):
        if "-" in part:
            low, high = part.split("-")
            days.update(range(int(low), int(high) + 1))
        elif part.strip():
            days.add(int(part))
    return days


def is_business_hours(now=None):
    now = now or _now()
    try:
        start, end = (
            datetime.strptime(t.strip(), "%H:%M").time() for t in Config.BUSINESS_HOURS.split("-")
        )
        return now.weekday() in _parse_days(Config.BUSINESS_DAYS) and start <= now.time() < end
    except ValueError:
        logger.error(f"Invalid BUSINESS_DAYS/BUSINESS_HOURS, treating as open")
        return True


def _hours_text(call):
    return Config.BUSINESS_HOURS_TEXT_EN if _language(call) == "en" else Config.BUSINESS_HOURS_TEXT_DE


# --- Step renderers ----------------------------------------------------------

def render_menu(response, call, attempt=1):
    gather = _gather(response, "menu_input", num_digits=1, attempt=attempt)
    _say(gather, call, "menu")


def render_order_number(response, call, attempt=1):
    gather = _gather(response, "order_number_input", timeout=NUMBER_TIMEOUT, attempt=attempt)
    _say(gather, call, "order_number")


def render_plz(response, call, order, attempt=1):
    gather = _gather(response, "plz_input", timeout=NUMBER_TIMEOUT, order=order, attempt=attempt)
    _say(gather, call, "plz")


def render_next_menu(response, call, order="", verified=0, kind="status", attempt=1):
    gather = _gather(
        response,
        "next_input",
        num_digits=1,
        finish_on_key="",  # let '*' and '#' through as choices
        order=order,
        verified=verified,
        kind=kind,
        attempt=attempt,
    )
    _say(gather, call, "next_menu" if kind == "status" else "not_found_menu")


def render_voicemail(response, call):
    text = _say(response, call, "voicemail")
    _event(call, EVENT_VOICEMAIL, bot_response=text)
    response.record(
        max_length=VOICEMAIL_MAX_LENGTH,
        finish_on_key="#",
        timeout=5,
        play_beep=True,
        action="/webhook/recorded",
        method="POST",
        recording_status_callback="/webhook/recording_status",
        transcribe=not uses_external_transcription(),
        transcribe_callback="/webhook/transcription",
    )


def render_agent(response, call):
    """Transfer to the team in business hours; otherwise (or if nobody answers) voicemail"""
    _event(call, EVENT_AGENT_REQUESTED)
    if not is_business_hours() or not Config.AGENT_NUMBERS:
        text = _say(response, call, "agent_after_hours", hours=_hours_text(call))
        _event(call, EVENT_AFTER_HOURS, bot_response=text)
        render_voicemail(response, call)
        return

    _say(response, call, "agent_connecting")
    dial = response.dial(
        timeout=Config.AGENT_DIAL_TIMEOUT,
        action=url_for("flow.agent_result"),
        method="POST",
        # Show our Twilio number: Twilio rejects unverified caller IDs
        caller_id=request.form.get("To") or None,
    )
    for number in Config.AGENT_NUMBERS:
        dial.number(number)


def speak_status(response, call, number, order_data, verified):
    """Status sentence(s) for a found order, then the follow-up menu"""
    spoken_number = status.number_for_speech(number)
    language = _language(call)
    order_date = status.parse_order_date(order_data.get("order_date"))

    if order_date is None:
        text = _say(response, call, "status_unverified", number=spoken_number)
        _event(call, EVENT_STATUS, user_input="no_order_date", bot_response=text)
        render_next_menu(response, call, order=number, verified=int(verified))
        return

    window = status.delivery_window(order_date)
    stage = status.delivery_stage(window)

    if stage == status.STAGE_OVERDUE:
        text = _say(response, call, "status_overdue")
        _event(call, EVENT_OVERDUE, user_input=number, bot_response=text)
        update_call_status(call.id, CallStatus.PROBLEM)
        render_agent(response, call)
        return

    if not verified:
        text = _say(response, call, "status_unverified", number=spoken_number)
    else:
        start, end = (status.date_for_speech(day, language) for day in window)
        key = "status_production" if stage == status.STAGE_PRODUCTION else "status_delivery_soon"
        text = _say(response, call, key, number=spoken_number, start=start, end=end)
        amount = status.open_amount(order_data)
        if amount > 0:
            text += " " + _say(
                response, call, "status_open_amount",
                amount=status.euro_for_speech(amount, language),
            )
    _event(call, EVENT_STATUS, user_input=f"{number} verified={int(verified)}", bot_response=text)
    update_call_status(call.id, CallStatus.COMPLETED)
    render_next_menu(response, call, order=number, verified=int(verified))


def _save_order(call, number, order_data, verification=None):
    order = Order(call_id=call.id, order_number=number)
    if order_data:
        order_date = status.parse_order_date(order_data.get("order_date"))
        order.status = "Found in AfterBuy"
        order.notes = f"Verification: {verification or 'pending'}"
        if order_date:
            start, end = status.delivery_window(order_date)
            order.promised_delivery_date = start + (end - start) / 2
    else:
        order.status = "Not Found"
        order.notes = "Order not found in AfterBuy"
    db.session.add(order)
    db.session.commit()


def _goodbye(response, call):
    text = _say(response, call, "goodbye")
    _event(call, EVENT_GOODBYE, bot_response=text)
    response.hangup()


# --- Webhooks ----------------------------------------------------------------

@twiml_route("/webhook/voice")
def incoming_call():
    caller = request.form.get("From", "")
    call_sid = request.form.get("CallSid", "")
    logger.info(f"Incoming call {call_sid} from {caller}")
    call = create_or_get_call(call_sid, caller, detect_language(caller))

    response = VoiceResponse()
    text = _say(response, call, "greeting", company=Config.COMPANY_NAME)
    _event(call, EVENT_GREETING, bot_response=text)
    render_menu(response, call)
    return response


@twiml_route("/webhook/menu")
def menu_input():
    call = _current_call()
    digits, attempt = _digits(), _arg_int("attempt")
    response = VoiceResponse()
    if call is None:
        _goodbye(response, call)
        return response
    if digits:
        _event(call, EVENT_MENU, user_input=digits)

    if digits == "1":
        render_order_number(response, call)
    elif digits == "2":
        render_voicemail(response, call)
    elif digits == "0":
        render_agent(response, call)
    elif digits == "9":
        call.language = "de" if call.language == "en" else "en"
        db.session.commit()
        render_menu(response, call)
    elif attempt < MAX_ATTEMPTS:
        if digits:
            _say(response, call, "menu_retry")
        render_menu(response, call, attempt + 1)
    else:
        # Caller is stuck in the menu: a human helps best
        render_agent(response, call)
    return response


@twiml_route("/webhook/order-number")
def order_number_input():
    call = _current_call()
    number = "".join(ch for ch in _digits() if ch.isdigit())
    attempt = _arg_int("attempt")
    response = VoiceResponse()
    if call is None:
        _goodbye(response, call)
        return response

    if not number:
        if attempt < MAX_ATTEMPTS:
            _say(response, call, "order_number_retry")
            render_order_number(response, call, attempt + 1)
        else:
            render_agent(response, call)
        return response

    _event(call, EVENT_ORDER_INPUT, user_input=number)
    order_data = get_order_from_afterbuy(number)

    if not order_data:
        _save_order(call, number, None)
        spoken = status.number_for_speech(number)
        if attempt < MAX_ATTEMPTS:
            text = _say(response, call, "not_found_retry", number=spoken)
            _event(call, EVENT_ORDER_NOT_FOUND, user_input=number, bot_response=text)
            render_order_number(response, call, attempt + 1)
        else:
            text = _say(response, call, "not_found_final", number=spoken)
            _event(call, EVENT_ORDER_NOT_FOUND, user_input=number, bot_response=text)
            render_next_menu(response, call, kind="not_found")
        return response

    _event(call, EVENT_ORDER_FOUND, user_input=number)
    if status.phone_matches(call.phone_number, status.order_phone(order_data)):
        _save_order(call, number, order_data, "phone")
        _event(call, EVENT_VERIFIED, user_input="phone")
        speak_status(response, call, number, order_data, verified=True)
    elif status.order_postal_code(order_data):
        _save_order(call, number, order_data, "postal_code_requested")
        render_plz(response, call, number)
    else:
        _save_order(call, number, order_data, "none_possible")
        _event(call, EVENT_NOT_VERIFIED, user_input="no_phone_or_postal_code")
        speak_status(response, call, number, order_data, verified=False)
    return response


@twiml_route("/webhook/plz")
def plz_input():
    call = _current_call()
    number = request.args.get("order", "")
    attempt = _arg_int("attempt")
    response = VoiceResponse()
    order_data = get_order_from_afterbuy(number) if number else None
    if call is None or not order_data:
        render_agent(response, call) if call else _goodbye(response, call)
        return response

    if status.postal_code_matches(_digits(), status.order_postal_code(order_data)):
        _event(call, EVENT_VERIFIED, user_input="postal_code")
        speak_status(response, call, number, order_data, verified=True)
    elif attempt < MAX_ATTEMPTS:
        _say(response, call, "plz_retry")
        render_plz(response, call, number, attempt + 1)
    else:
        _event(call, EVENT_NOT_VERIFIED, user_input="postal_code_mismatch")
        speak_status(response, call, number, order_data, verified=False)
    return response


@twiml_route("/webhook/next")
def next_input():
    call = _current_call()
    digits = _digits()
    number = request.args.get("order", "")
    verified = request.args.get("verified") == "1"
    kind = request.args.get("kind", "status")
    attempt = _arg_int("attempt")
    response = VoiceResponse()
    if call is None:
        _goodbye(response, call)
        return response
    if digits:
        _event(call, EVENT_MENU, user_input=f"next:{digits}")

    if digits == "*" and kind == "status" and number:
        order_data = get_order_from_afterbuy(number)
        if order_data:
            speak_status(response, call, number, order_data, verified)
        else:
            render_next_menu(response, call, order=number, verified=int(verified))
    elif digits == "1":
        render_order_number(response, call)
    elif digits == "2":
        render_voicemail(response, call)
    elif digits == "0":
        render_agent(response, call)
    elif attempt < MAX_ATTEMPTS:
        if digits:
            _say(response, call, "menu_retry")
        render_next_menu(response, call, number, int(verified), kind, attempt + 1)
    else:
        _goodbye(response, call)
    return response


@twiml_route("/webhook/agent-result")
def agent_result():
    call = _current_call()
    dial_status = request.form.get("DialCallStatus", "")
    response = VoiceResponse()
    if dial_status in ("completed", "answered"):
        _event(call, EVENT_AGENT_CONNECTED, user_input=dial_status)
        if call:
            update_call_status(call.id, CallStatus.COMPLETED)
        response.hangup()
        return response

    logger.info(f"Team did not answer ({dial_status}), offering voicemail")
    text = _say(response, call, "agent_no_answer")
    _event(call, EVENT_AGENT_NO_ANSWER, user_input=dial_status, bot_response=text)
    render_voicemail(response, call)
    return response
