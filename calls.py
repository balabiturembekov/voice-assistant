"""
Call records and the conversation/event log
"""
import logging

from models import Call, CallStatus, Conversation, db

logger = logging.getLogger(__name__)


def create_or_get_call(call_sid, phone_number, language):
    """Create or get existing call record"""
    if not call_sid:
        logger.error("create_or_get_call called with empty call_sid")
        raise ValueError("call_sid cannot be empty")

    call = Call.query.filter_by(call_sid=call_sid).first()
    if not call:
        call = Call(
            call_sid=call_sid,
            phone_number=phone_number or "",
            language=language or "de",
            status=CallStatus.PROCESSING,
        )
        try:
            db.session.add(call)
            db.session.commit()
            logger.info(f"Created new call record: {call_sid}")
        except Exception as e:
            logger.error(f"Error creating call record: {str(e)}")
            db.session.rollback()
            # Try to get existing call again in case of race condition
            call = Call.query.filter_by(call_sid=call_sid).first()
            if not call:
                raise
    return call


def log_conversation(call_id, step, user_input=None, bot_response=None):
    """Log conversation step"""
    if not call_id:
        logger.error(f"log_conversation called with empty call_id for step: {step}")
        return

    conversation = Conversation(
        call_id=call_id, step=step, user_input=user_input, bot_response=bot_response
    )
    try:
        db.session.add(conversation)
        db.session.commit()
        logger.info(f"Logged conversation: {step}")
    except Exception as e:
        logger.error(f"Error logging conversation: {str(e)}, step: {step}")
        db.session.rollback()
        # Continue execution even if logging fails


def update_call_status(call_id, status):
    """Update call status"""
    if not call_id:
        logger.error("update_call_status called with empty call_id")
        return

    call = db.session.get(Call, call_id)
    if call:
        try:
            call.status = status
            db.session.commit()
            logger.info(f"Updated call {call_id} status to {status.value}")
        except Exception as e:
            logger.error(f"Error updating call status: {str(e)}, call_id: {call_id}")
            db.session.rollback()
            # Continue execution even if update fails
