"""
Call funnel for the dashboard, built from the call flow events (Conversation.step)
"""
from datetime import timedelta

from sqlalchemy import distinct, func

import call_flow as flow
from models import Call, Conversation, db, utcnow


def _calls_with(step, since):
    return set(
        row[0]
        for row in db.session.query(distinct(Conversation.call_id))
        .join(Call, Call.id == Conversation.call_id)
        .filter(Conversation.step == step, Call.created_at >= since)
    )


def funnel_stats(days=30):
    """Counts of calls per stage of the IVR over the last `days` days"""
    since = utcnow() - timedelta(days=days)
    total = db.session.query(func.count(Call.id)).filter(Call.created_at >= since).scalar()

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
        "total": total,
        "left_in_menu": total - len(menu),
        "order_input": len(order_input),
        "order_found": len(found),
        "status_spoken": len(status),
        "overdue": len(overdue),
        # Got their answer without a human or a voicemail
        "self_service": len(status - agent - voicemail),
        "agent_requested": len(agent),
        "agent_connected": len(connected),
        "voicemail": len(voicemail),
    }
