"""
Template helpers for the console: human labels and status tones (icon + label)
"""
import re
from datetime import date

from flask import request, url_for

from models import CallStatus

# Call status -> (tone, icon)
CALL_STATUS_STYLE = {
    CallStatus.PROCESSING: ("warning", "fa-clock"),
    CallStatus.COMPLETED: ("good", "fa-circle-check"),
    CallStatus.HANDLED: ("good", "fa-user-check"),
    CallStatus.PROBLEM: ("serious", "fa-circle-exclamation"),
}

# Staff-managed order status
ORDER_STATUS_STYLE = {
    "delivered": ("good", "fa-circle-check"),
    "shipped": ("info", "fa-truck"),
    "cancelled": ("neutral", "fa-ban"),
}

LOOKUP_STYLE = {
    "found": ("good", "fa-circle-check", "Found in Afterbuy"),
    "not_found": ("warning", "fa-magnifying-glass", "Not found"),
}

# value -> (tone, icon, label, explanation)
VERIFICATION_STYLE = {
    "phone": ("good", "fa-phone", "Phone matched", "Called from the phone number on the order."),
    "postal_code": ("good", "fa-location-dot", "Postcode matched", "Caller entered the billing postcode."),
    "pending": ("neutral", "fa-hourglass-half", "Not completed", "Postcode was requested, but the caller hung up."),
    "failed": ("serious", "fa-shield-halved", "Failed", "Postcode didn't match twice. Lisa shared no details."),
    "not_possible": ("warning", "fa-circle-question", "Not possible",
                     "The order has no phone or postcode to check. Lisa shared no details."),
}

# Conversation.step -> (label, icon, actor); actor is "lisa", "caller" or "system"
STEP_STYLE = {
    "ivr_greeting": ("Greeting", "fa-wave-square", "lisa"),
    "greeting": ("Greeting", "fa-wave-square", "lisa"),
    "menu_choice": ("Menu choice", "fa-grip", "caller"),
    "ivr_order_number": ("Order number entered", "fa-hashtag", "caller"),
    "order_input": ("Order number entered", "fa-hashtag", "caller"),
    "order_found": ("Order found", "fa-box", "system"),
    "order_not_found": ("Order not found", "fa-magnifying-glass", "system"),
    "verified": ("Caller verified", "fa-shield-halved", "system"),
    "not_verified": ("Caller not verified", "fa-shield", "system"),
    "status_spoken": ("Status shared", "fa-comment-dots", "lisa"),
    "status_overdue": ("Delivery overdue", "fa-triangle-exclamation", "lisa"),
    "agent_requested": ("Transfer to team", "fa-headset", "system"),
    "agent_after_hours": ("Outside business hours", "fa-moon", "lisa"),
    "agent_connected": ("Connected to team", "fa-phone-volume", "system"),
    "agent_no_answer": ("Team didn't answer", "fa-phone-slash", "system"),
    "voicemail_started": ("Voice message requested", "fa-microphone", "lisa"),
    "voice_message_recorded": ("Voice message recorded", "fa-microphone-lines", "caller"),
    "voice_message_failed": ("Voice message failed", "fa-microphone-slash", "system"),
    "goodbye": ("Goodbye", "fa-hand", "lisa"),
    "ivr_next_choice": ("Follow-up choice", "fa-grip", "caller"),
    "ivr_plz_requested": ("Postcode requested", "fa-location-dot", "lisa"),
    "ivr_plz_mismatch": ("Postcode didn't match", "fa-location-crosshairs", "caller"),
    "ivr_no_input": ("No input", "fa-volume-xmark", "caller"),
}

MAIN_MENU = {
    "1": "Pressed 1 · order status",
    "2": "Pressed 2 · leave a message",
    "0": "Pressed 0 · speak to the team",
    "9": "Pressed 9 · switch language",
}
NEXT_MENU = {
    "*": "Pressed * · repeat the status",
    "1": "Pressed 1 · another order",
    "2": "Pressed 2 · leave a message",
    "0": "Pressed 0 · speak to the team",
}
INPUT_STEPS = {
    "menu": "main menu",
    "order_number": "order number",
    "next": "follow-up menu",
}
AGENT_REASONS = {
    "caller_choice": "Caller asked for the team",
    "no_input": "No input from the caller",
    "overdue": "Delivery is overdue",
    "menu_not_understood": "Caller's choices were not understood",
}
VERIFICATION = {
    "phone": "Caller's phone matches the order",
    "postal_code": "Postcode matched the billing address",
    "postal_code_mismatch": "Postcode didn't match twice · no details shared",
    "no_phone_or_postal_code": "Order has no phone or postcode to check · no details shared",
}


def call_status_style(status):
    tone, icon = CALL_STATUS_STYLE.get(status, ("neutral", "fa-circle"))
    return {"tone": tone, "icon": icon, "label": status.value if status else "Unknown"}


def order_status_style(status):
    if not status:
        return {"tone": "neutral", "icon": "fa-minus", "label": "Not set"}
    tone, icon = ORDER_STATUS_STYLE.get(status.strip().lower(), ("info", "fa-circle-info"))
    return {"tone": tone, "icon": icon, "label": status}


def lookup_style(result):
    tone, icon, label = LOOKUP_STYLE.get(result, ("neutral", "fa-minus", "Unknown"))
    return {"tone": tone, "icon": icon, "label": label}


def verification_style(value):
    tone, icon, label, explanation = VERIFICATION_STYLE.get(
        value, ("neutral", "fa-minus", "—", "Order was not found, so there was nothing to verify.")
    )
    return {"tone": tone, "icon": icon, "label": label, "explanation": explanation}


def is_overdue(order):
    return bool(
        order.lookup_result == "found"
        and order.promised_delivery_date
        and order.promised_delivery_date < date.today()
        and (order.status or "").strip().lower() not in ("delivered", "cancelled")
    )


def money(amount):
    """1680.5 -> '1.680,50 €' (German format for the office)"""
    if amount is None:
        return "—"
    text = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


def step_style(step):
    label, icon, actor = STEP_STYLE.get(
        step, (step.replace("_", " ").capitalize(), "fa-circle", "system")
    )
    return {"label": label, "icon": icon, "actor": actor}


def event_detail(step, value):
    """Human-readable text for Conversation.user_input; None = show nothing extra.

    Returns (text, is_code): is_code=True keeps monospace (order numbers, raw values).
    """
    if not value:
        return None
    attempt = re.search(r"attempt=(\d+)", value)
    attempt_text = f"attempt {attempt.group(1)} of 2" if attempt else ""

    if step == "menu_choice":
        if value.startswith("next:"):  # pre-1.1 format
            return NEXT_MENU.get(value[5:], f"Pressed {value[5:]}"), False
        return MAIN_MENU.get(value, f"Pressed {value} · not a menu option"), False
    if step == "ivr_next_choice":
        return NEXT_MENU.get(value, f"Pressed {value} · not a menu option"), False
    if step == "ivr_no_input":
        where = INPUT_STEPS.get(value.split()[0], value.split()[0])
        return f"Nothing entered in the {where} · {attempt_text}", False
    if step in ("ivr_plz_requested", "ivr_plz_mismatch"):
        number = value.split()[0]
        text = f"Order {number} · {attempt_text}"
        if "no_input" in value:
            text += " · nothing entered"
        return text, False
    if step in ("verified", "not_verified"):
        return VERIFICATION.get(value, value), False
    if step == "status_spoken":
        if value == "no_order_date":
            return "Order has no date · shared without details", False
        verified = value == "verified" or value.endswith("verified=1")
        return ("Shared delivery window and open balance" if verified
                else "Shared without details (caller not verified)"), False
    if step == "agent_requested":
        return AGENT_REASONS.get(value, value), False
    if step in ("agent_connected", "agent_no_answer"):
        return {"completed": "Call answered", "answered": "Call answered", "no-answer": "Nobody answered",
                "busy": "Line busy", "failed": "Call failed", "canceled": "Caller hung up"}.get(value, value), False
    return value, True


# Audit action -> (tone, icon, sentence with {actor}/{target}/{detail})
AUDIT_STYLE = {
    "sign_in": ("good", "fa-right-to-bracket", "{target} signed in"),
    "sign_in_failed": ("warning", "fa-triangle-exclamation", "Failed sign-in as “{detail}”"),
    "sign_in_throttled": ("serious", "fa-ban", "Sign-in blocked after too many attempts (“{detail}”)"),
    "user_created": ("info", "fa-user-plus", "{actor} added {target} as {detail}"),
    "user_updated": ("info", "fa-user-pen", "{actor} changed {target}: {detail}"),
    "user_disabled": ("serious", "fa-user-slash", "{actor} disabled {target}"),
    "user_enabled": ("good", "fa-user-check", "{actor} enabled {target}"),
    "password_reset": ("warning", "fa-key", "{actor} set a temporary password for {target}"),
    "password_changed": ("good", "fa-lock", "{target} changed their password"),
    "calls_deleted": ("serious", "fa-trash-can", "{actor} deleted {detail}"),
    "order_deleted": ("serious", "fa-trash-can", "{actor} deleted {detail}"),
}


def audit_text(event):
    tone, icon, template = AUDIT_STYLE.get(event.action, ("neutral", "fa-circle", event.action))
    text = template.format(
        actor=event.actor.username if event.actor else "System",
        target=event.target.username if event.target else "unknown user",
        detail=event.detail or "",
    )
    return {"tone": tone, "icon": icon, "text": text}


def page_url(page):
    """Current URL with another page number, keeping the filters"""
    args = request.args.to_dict()
    args["page"] = page
    return url_for(request.endpoint, **request.view_args, **args)


def register(app):
    app.jinja_env.globals.update(
        call_status_style=call_status_style,
        order_status_style=order_status_style,
        lookup_style=lookup_style,
        verification_style=verification_style,
        is_overdue=is_overdue,
        money=money,
        step_style=step_style,
        event_detail=event_detail,
        audit_text=audit_text,
        page_url=page_url,
        CallStatus=CallStatus,
    )
