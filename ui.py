"""
Template helpers for the console: human labels and status tones (icon + label)
"""
from flask import request, url_for

from models import CallStatus

# Call status -> (tone, icon)
CALL_STATUS_STYLE = {
    CallStatus.PROCESSING: ("warning", "fa-clock"),
    CallStatus.COMPLETED: ("good", "fa-circle-check"),
    CallStatus.HANDLED: ("good", "fa-user-check"),
    CallStatus.PROBLEM: ("serious", "fa-circle-exclamation"),
}

ORDER_STATUS_STYLE = {
    "found in afterbuy": ("good", "fa-circle-check"),
    "delivered": ("good", "fa-circle-check"),
    "shipped": ("info", "fa-truck"),
    "not found": ("warning", "fa-magnifying-glass"),
    "overdue delivery": ("serious", "fa-triangle-exclamation"),
    "cancelled": ("neutral", "fa-ban"),
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
}


def call_status_style(status):
    tone, icon = CALL_STATUS_STYLE.get(status, ("neutral", "fa-circle"))
    return {"tone": tone, "icon": icon, "label": status.value if status else "Unknown"}


def order_status_style(status):
    tone, icon = ORDER_STATUS_STYLE.get((status or "").strip().lower(), ("info", "fa-circle-info"))
    return {"tone": tone, "icon": icon, "label": status or "Unknown"}


def step_style(step):
    label, icon, actor = STEP_STYLE.get(
        step, (step.replace("_", " ").capitalize(), "fa-circle", "system")
    )
    return {"label": label, "icon": icon, "actor": actor}


def page_url(page):
    """Current URL with another page number, keeping the filters"""
    args = request.args.to_dict()
    args["page"] = page
    return url_for(request.endpoint, **request.view_args, **args)


def register(app):
    app.jinja_env.globals.update(
        call_status_style=call_status_style,
        order_status_style=order_status_style,
        step_style=step_style,
        page_url=page_url,
        CallStatus=CallStatus,
    )
