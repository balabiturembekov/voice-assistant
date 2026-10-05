"""
Dashboard data built from calls and the call flow events (Conversation.step)
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import distinct, func

import call_flow as flow
from models import Call, CallStatus, Conversation, EmailStatus, VoiceMessage, db, utcnow

# First matching event decides the call outcome shown in the dashboard
OUTCOMES = [
    (flow.EVENT_AGENT_CONNECTED, "Connected to team", "good"),
    (flow.EVENT_VOICEMAIL, "Voice message", "info"),
    (flow.EVENT_OVERDUE, "Delivery overdue", "serious"),
    (flow.EVENT_AGENT_NO_ANSWER, "Team didn't answer", "warning"),
    (flow.EVENT_STATUS, "Status shared", "good"),
    (flow.EVENT_ORDER_NOT_FOUND, "Order not found", "warning"),
    (flow.EVENT_AGENT_REQUESTED, "Transferred to team", "info"),
    (flow.EVENT_MENU, "Left during the call", "neutral"),
    (flow.EVENT_GREETING, "Hung up in menu", "neutral"),
]


def _calls_with(step, since):
    return set(
        row[0]
        for row in db.session.query(distinct(Conversation.call_id))
        .join(Call, Call.id == Conversation.call_id)
        .filter(Conversation.step == step, Call.created_at >= since)
    )


def funnel_stats(days=30):
    """Counts of IVR (v2) calls per stage over the last `days` days"""
    since = utcnow() - timedelta(days=days)
    calls = _calls_with(flow.EVENT_GREETING, since)
    menu = _calls_with(flow.EVENT_MENU, since)
    order_input = _calls_with(flow.EVENT_ORDER_INPUT, since)
    found = _calls_with(flow.EVENT_ORDER_FOUND, since)
    status = _calls_with(flow.EVENT_STATUS, since)
    overdue = _calls_with(flow.EVENT_OVERDUE, since)
    agent = _calls_with(flow.EVENT_AGENT_REQUESTED, since)
    connected = _calls_with(flow.EVENT_AGENT_CONNECTED, since)
    voicemail = _calls_with(flow.EVENT_VOICEMAIL, since)

    return {
        "days": days,
        "total": len(calls),
        "left_in_menu": len(calls - menu),
        "order_input": len(order_input & calls),
        "order_found": len(found & calls),
        "status_spoken": len(status & calls),
        "overdue": len(overdue & calls),
        # Got their answer without a human or a voicemail
        "self_service": len((status - agent - voicemail) & calls),
        "agent_requested": len(agent & calls),
        "agent_connected": len(connected & calls),
        "voicemail": len(voicemail & calls),
    }


def calls_per_day(days=14):
    """[(date, count)] for the last `days` days, oldest first, zero-filled"""
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    rows = (
        db.session.query(func.date(Call.created_at), func.count(Call.id))
        .filter(Call.created_at >= start)
        .group_by(func.date(Call.created_at))
        .all()
    )
    counts = {str(day): count for day, count in rows}
    return [
        (start + timedelta(days=i), counts.get(str(start + timedelta(days=i)), 0))
        for i in range(days)
    ]


def call_outcomes(call_ids):
    """{call_id: (label, tone)} from each call's events"""
    steps = defaultdict(set)
    if call_ids:
        for call_id, step in db.session.query(Conversation.call_id, Conversation.step).filter(
            Conversation.call_id.in_(call_ids)
        ):
            steps[call_id].add(step)
    outcomes = {}
    for call_id in call_ids:
        outcomes[call_id] = next(
            ((label, tone) for event, label, tone in OUTCOMES if event in steps[call_id]),
            ("Legacy flow", "neutral"),
        )
    return outcomes


# A postcode guessed wrong this often for one order looks like someone probing
SUSPICIOUS_ATTEMPTS = 3


def verification_failures(days=30, limit=5):
    """Orders with failed postcode checks: [{number, attempts, calls, last, suspicious}]"""
    since = utcnow() - timedelta(days=days)
    rows = (
        db.session.query(Conversation.user_input, Conversation.call_id, Conversation.timestamp)
        .filter(Conversation.step == flow.EVENT_PLZ_MISMATCH, Conversation.timestamp >= since)
        .all()
    )
    by_order = {}
    for value, call_id, timestamp in rows:
        number = (value or "").split()[0] if value else ""
        if not number:
            continue
        item = by_order.setdefault(number, {"number": number, "attempts": 0, "calls": set(), "last": timestamp})
        item["attempts"] += 1
        item["calls"].add(call_id)
        item["last"] = max(item["last"], timestamp)
    items = []
    for item in by_order.values():
        item["calls"] = len(item["calls"])
        item["suspicious"] = item["attempts"] >= SUSPICIOUS_ATTEMPTS
        items.append(item)
    items.sort(key=lambda i: (i["suspicious"], i["attempts"], i["last"]), reverse=True)
    return {"total_attempts": sum(i["attempts"] for i in items), "orders": items[:limit],
            "order_count": len(items), "suspicious": sum(i["suspicious"] for i in items)}


def dashboard_data(days=30):
    since = utcnow() - timedelta(days=days)
    funnel = funnel_stats(days)
    recent_calls = Call.query.order_by(Call.created_at.desc()).limit(8).all()
    voice_messages = VoiceMessage.query.order_by(VoiceMessage.created_at.desc()).limit(5).all()
    failed_emails = VoiceMessage.query.filter(
        VoiceMessage.email_status == EmailStatus.FAILED
    ).count()
    problems = Call.query.filter(
        Call.status == CallStatus.PROBLEM, Call.created_at >= since
    ).count()
    total = funnel["total"]
    return {
        "calls_total": Call.query.filter(Call.created_at >= since).count(),
        "funnel": funnel,
        "self_service_rate": round(100 * funnel["self_service"] / total) if total else None,
        "daily": calls_per_day(14),
        "recent_calls": recent_calls,
        "outcomes": call_outcomes([c.id for c in recent_calls]),
        "voice_messages": voice_messages,
        "failed_emails": failed_emails,
        "problems": problems,
        "verification": verification_failures(days),
    }
