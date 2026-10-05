"""
Permanent deletion of calls and everything that belongs to them.

A call is deleted together with its conversation events, voice messages, the
recordings at Twilio and the order lookups. If a recording can't be deleted at
Twilio, that call is kept so no recording is orphaned without a reference.
"""
import logging

from models import Call, Conversation, Order, VoiceMessage, db
from recordings import RecordingUnavailable, delete_recording

logger = logging.getLogger(__name__)


def deletion_summary(call_ids):
    """What a deletion would remove, for the confirmation dialog"""
    ids = list(call_ids)
    if not ids:
        return {"calls": 0, "voice_messages": 0, "orders": 0, "events": 0}
    return {
        "calls": Call.query.filter(Call.id.in_(ids)).count(),
        "voice_messages": VoiceMessage.query.filter(VoiceMessage.call_id.in_(ids)).count(),
        "orders": Order.query.filter(Order.call_id.in_(ids)).count(),
        "events": Conversation.query.filter(Conversation.call_id.in_(ids)).count(),
    }


def delete_calls(call_ids):
    """Delete calls with all related data. Returns {"deleted": [...ids], "failed": {id: reason}}"""
    deleted, failed = [], {}
    for call in Call.query.filter(Call.id.in_(list(call_ids))).all():
        try:
            for message in call.voice_messages:
                delete_recording(message.recording_url)
        except RecordingUnavailable as e:
            failed[call.id] = f"recording could not be deleted at Twilio ({e})"
            logger.error(f"Call {call.id} kept: {failed[call.id]}")
            continue

        # Orders have no ORM cascade; conversations and voice messages do
        Order.query.filter_by(call_id=call.id).delete(synchronize_session=False)
        db.session.delete(call)
        db.session.commit()
        deleted.append(call.id)
    logger.info(f"Deleted {len(deleted)} call(s); {len(failed)} kept because of errors")
    return {"deleted": deleted, "failed": failed}


def delete_order(order):
    """Delete one order lookup (the call stays)"""
    db.session.delete(order)
    db.session.commit()
