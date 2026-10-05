"""
GDPR retention: strip personal data from old calls, keep the statistics
"""
import logging
from datetime import timedelta

from models import Call, Conversation, Order, VoiceMessage, db, utcnow

logger = logging.getLogger(__name__)

ANONYMIZED_PHONE = "anonymized"


def anonymize_calls_older_than(days):
    """Remove phone numbers, dialog texts, transcriptions and recording links"""
    cutoff = utcnow() - timedelta(days=days)
    calls = Call.query.filter(Call.created_at < cutoff, Call.anonymized_at.is_(None)).all()
    now = utcnow()
    for call in calls:
        call.phone_number = ANONYMIZED_PHONE
        call.anonymized_at = now
        Conversation.query.filter_by(call_id=call.id).update(
            {"user_input": None, "bot_response": None}, synchronize_session=False
        )
        VoiceMessage.query.filter_by(call_id=call.id).update(
            {"transcription_text": None, "recording_url": None}, synchronize_session=False
        )
        # Notes hold customer names, transcriptions and recording links
        Order.query.filter_by(call_id=call.id).update(
            {"notes": None}, synchronize_session=False
        )
    db.session.commit()
    logger.info(f"Anonymized {len(calls)} call(s) older than {days} days")
    return len(calls)
