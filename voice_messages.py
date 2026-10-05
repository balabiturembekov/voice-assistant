"""
Voice message lifecycle: store the recording, attach the transcription,
send exactly one notification email per recording (via the job queue).
"""
import logging
from datetime import timedelta

from sqlalchemy import or_, update

from config import Config
from jobs_queue import enqueue
from models import EmailStatus, Order, VoiceMessage, db, utcnow
from services import send_voice_message_email

logger = logging.getLogger(__name__)

NO_TRANSCRIPTION_TEXT = "(Transkription nicht verfügbar / Transcription not available)"
# A SENDING row older than this is treated as a crashed attempt
STALE_SENDING_AFTER = timedelta(minutes=10)
EXTERNAL_TRANSCRIPTION_SERVICES = ("google", "deepgram")
MAX_EMAIL_ATTEMPTS = 10


def uses_external_transcription():
    return Config.TRANSCRIPTION_SERVICE in EXTERNAL_TRANSCRIPTION_SERVICES


def _latest_order(call_id):
    return (
        Order.query.filter_by(call_id=call_id).order_by(Order.created_at.desc()).first()
    )


def upsert_voice_message(call, recording_sid, **fields):
    """Create or update the VoiceMessage for a RecordingSid; empty values are ignored"""
    message = VoiceMessage.query.filter_by(recording_sid=recording_sid).first()
    if message is None:
        message = VoiceMessage(call_id=call.id, recording_sid=recording_sid)
        db.session.add(message)
    for name, value in fields.items():
        if value not in (None, ""):
            setattr(message, name, value)
    db.session.commit()
    return message


def set_transcription(message, text, status, source):
    """Store a transcription unless a better (external) one is already there"""
    if message.transcription_source in EXTERNAL_TRANSCRIPTION_SERVICES and source == "twilio":
        return message
    message.transcription_status = status
    if text:
        message.transcription_text = text
        message.transcription_source = source
    db.session.commit()
    return message


# --- Queue helpers (never let queue problems break a Twilio webhook) ---------

def queue_email(message_id, allow_without_transcription=False, delay_seconds=0):
    try:
        enqueue(
            send_voice_message_email_job,
            message_id,
            allow_without_transcription,
            delay_seconds=delay_seconds,
        )
    except Exception as e:
        logger.error(f"Could not queue email for voice message {message_id}: {e}")


def queue_external_transcription(message_id):
    try:
        enqueue(transcribe_voice_message_job, message_id)
    except Exception as e:
        logger.error(f"Could not queue transcription for voice message {message_id}: {e}")


# --- Jobs (run in the RQ worker) ---------------------------------------------

def _app_context():
    from app import app

    return app.app_context()


def _claim_for_sending(message_id):
    """Atomically move PENDING/FAILED (or stale SENDING) to SENDING; True if we won"""
    stale_before = utcnow() - STALE_SENDING_AFTER
    result = db.session.execute(
        update(VoiceMessage)
        .where(
            VoiceMessage.id == message_id,
            or_(
                VoiceMessage.email_status.in_([EmailStatus.PENDING, EmailStatus.FAILED]),
                (VoiceMessage.email_status == EmailStatus.SENDING)
                & (VoiceMessage.updated_at < stale_before),
            ),
        )
        .values(
            email_status=EmailStatus.SENDING,
            email_attempts=VoiceMessage.email_attempts + 1,
            updated_at=utcnow(),
        )
    )
    db.session.commit()
    return result.rowcount == 1


def send_voice_message_email_job(message_id, allow_without_transcription=False):
    """Send the notification email once; raises on failure so RQ retries"""
    with _app_context():
        message = db.session.get(VoiceMessage, message_id)
        if message is None:
            logger.warning(f"Voice message {message_id} not found, skipping email")
            return "missing"
        if message.email_status == EmailStatus.SENT:
            return "already_sent"
        if not message.recording_url:
            logger.warning(f"Voice message {message_id} has no recording URL yet")
            return "no_recording"
        if not message.transcription_text and not allow_without_transcription:
            return "waiting_for_transcription"
        if not _claim_for_sending(message_id):
            return "already_in_progress"

        db.session.refresh(message)
        call = message.call
        order = _latest_order(call.id)
        try:
            sent = send_voice_message_email(
                caller_number=call.phone_number,
                recording_url=message.recording_url,
                transcription_text=message.transcription_text or NO_TRANSCRIPTION_TEXT,
                duration_seconds=message.duration_seconds or 0,
                language=call.language or "de",
                order_number=order.order_number if order else None,
            )
            error = None if sent else "send_voice_message_email returned False"
        except Exception as e:
            sent, error = False, str(e)

        if sent:
            message.email_status = EmailStatus.SENT
            message.email_sent_at = utcnow()
            message.email_last_error = None
            db.session.commit()
            logger.info(f"Voice message {message_id} email sent")
            return "sent"

        message.email_status = EmailStatus.FAILED
        message.email_last_error = error
        db.session.commit()
        logger.error(f"Voice message {message_id} email failed: {error}")
        raise RuntimeError(f"Email for voice message {message_id} failed: {error}")


def transcribe_voice_message_job(message_id):
    """Transcribe with the external service, then send the email"""
    from transcription_service import transcribe_with_external_service

    with _app_context():
        message = db.session.get(VoiceMessage, message_id)
        if message is None or not message.recording_url:
            return "missing"
        language = "de-DE" if (message.call.language or "de") == "de" else "en-US"
        text = transcribe_with_external_service(
            audio_url=message.recording_url,
            language=language,
            service=Config.TRANSCRIPTION_SERVICE,
        )
        if text:
            set_transcription(message, text, "completed", Config.TRANSCRIPTION_SERVICE)
        else:
            message.transcription_status = "failed"
            db.session.commit()
            logger.warning(f"External transcription empty for voice message {message_id}")

    queue_email(message_id, allow_without_transcription=True)
    return "done"


def retry_unsent_emails(older_than_seconds=None):
    """Safety net: queue emails stuck in PENDING/FAILED (e.g. Redis was down)"""
    if older_than_seconds is None:
        older_than_seconds = Config.VOICE_EMAIL_FALLBACK_DELAY * 2
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    stuck = VoiceMessage.query.filter(
        VoiceMessage.email_status.in_([EmailStatus.PENDING, EmailStatus.FAILED]),
        VoiceMessage.recording_url.isnot(None),
        VoiceMessage.created_at < cutoff,
        VoiceMessage.email_attempts < MAX_EMAIL_ATTEMPTS,
    ).all()
    for message in stuck:
        queue_email(message.id, allow_without_transcription=True)
    return len(stuck)
