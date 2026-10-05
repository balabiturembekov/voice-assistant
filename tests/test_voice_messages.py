from datetime import timedelta

import pytest

import voice_messages
from models import Call, EmailStatus, Order, VoiceMessage, db, utcnow
from tests.conftest import post_webhook

CALL_SID = "CAvoice1"
REC_SID = "RE111"
REC_URL = "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE111"


@pytest.fixture
def call(app):
    call = Call(call_sid=CALL_SID, phone_number="+4915112345678", language="de")
    db.session.add(call)
    db.session.commit()
    db.session.add(Order(call_id=call.id, order_number="24896241", status="Found"))
    db.session.commit()
    return call


@pytest.fixture
def sent_emails(monkeypatch):
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(voice_messages, "send_voice_message_email", fake_send)
    return sent


def record(client, duration="12"):
    return post_webhook(client, "/webhook/recorded", {
        "CallSid": CALL_SID, "RecordingSid": REC_SID, "RecordingUrl": REC_URL,
        "RecordingDuration": duration, "Digits": "#", "From": "+4915112345678",
    })


def recording_status(client):
    return post_webhook(client, "/webhook/recording_status", {
        "CallSid": CALL_SID, "RecordingSid": REC_SID, "RecordingUrl": REC_URL,
        "RecordingStatus": "completed", "RecordingDuration": "12",
    })


def transcription(client, text="Hallo, wo ist meine Lieferung?", status="completed"):
    return post_webhook(client, "/webhook/transcription", {
        "CallSid": CALL_SID, "RecordingSid": REC_SID, "RecordingUrl": REC_URL,
        "TranscriptionText": text, "TranscriptionStatus": status,
    })


def message():
    # Jobs commit through their own session; drop this session's cached rows
    db.session.expire_all()
    return VoiceMessage.query.filter_by(recording_sid=REC_SID).one()


def test_recording_is_stored_without_sending_email(client, call, sent_emails):
    resp = record(client)
    assert resp.status_code == 200
    assert b"Vielen Dank" in resp.data
    msg = message()
    assert msg.recording_url == REC_URL
    assert msg.duration_seconds == 12
    assert msg.finish_method == "user_pressed_hash"
    assert msg.email_status == EmailStatus.PENDING
    assert sent_emails == []


def test_recording_status_alone_does_not_send(client, call, sent_emails):
    # The fallback email is delayed; nothing goes out immediately
    assert recording_status(client).status_code == 200
    assert message().recording_url == REC_URL
    assert sent_emails == []


def test_full_flow_sends_exactly_one_email(client, call, sent_emails):
    record(client)
    recording_status(client)
    transcription(client)
    transcription(client)  # Twilio may retry callbacks

    assert len(sent_emails) == 1
    email = sent_emails[0]
    assert email["transcription_text"] == "Hallo, wo ist meine Lieferung?"
    assert email["recording_url"] == REC_URL
    assert email["order_number"] == "24896241"
    assert email["duration_seconds"] == 12
    msg = message()
    assert msg.email_status == EmailStatus.SENT
    assert msg.email_sent_at is not None


def test_failed_transcription_still_sends_email(client, call, sent_emails):
    record(client)
    transcription(client, text="", status="failed")
    assert len(sent_emails) == 1
    assert sent_emails[0]["transcription_text"] == voice_messages.NO_TRANSCRIPTION_TEXT


def test_transcription_before_recorded_callback(client, call, sent_emails):
    # Callbacks can arrive in any order
    transcription(client)
    record(client)
    assert len(sent_emails) == 1
    assert message().duration_seconds == 12


def test_smtp_failure_marks_failed_and_retry_succeeds(app, client, call, monkeypatch):
    monkeypatch.setattr(voice_messages, "send_voice_message_email", lambda **kw: False)
    record(client)
    transcription(client)
    msg = message()
    assert msg.email_status == EmailStatus.FAILED
    assert msg.email_attempts == 1

    sent = []
    monkeypatch.setattr(voice_messages, "send_voice_message_email", lambda **kw: sent.append(kw) or True)
    assert voice_messages.send_voice_message_email_job(msg.id) == "sent"
    assert len(sent) == 1
    db.session.refresh(msg)
    assert msg.email_status == EmailStatus.SENT
    assert msg.email_attempts == 2


def test_job_raises_on_failure_so_rq_retries(app, client, call, monkeypatch):
    monkeypatch.setattr(voice_messages, "send_voice_message_email", lambda **kw: False)
    record(client)
    msg_id = message().id
    with pytest.raises(RuntimeError):
        voice_messages.send_voice_message_email_job(msg_id, True)


def test_fallback_without_transcription(app, client, call, sent_emails):
    record(client)
    msg_id = message().id
    assert voice_messages.send_voice_message_email_job(msg_id) == "waiting_for_transcription"
    assert voice_messages.send_voice_message_email_job(msg_id, True) == "sent"
    assert voice_messages.send_voice_message_email_job(msg_id, True) == "already_sent"
    assert len(sent_emails) == 1


def test_concurrent_send_is_blocked(app, client, call, sent_emails):
    record(client)
    msg = message()
    msg.email_status = EmailStatus.SENDING
    db.session.commit()
    assert voice_messages.send_voice_message_email_job(msg.id, True) == "already_in_progress"
    assert sent_emails == []


def test_stale_sending_is_reclaimed(app, client, call, sent_emails):
    record(client)
    msg = message()
    msg.email_status = EmailStatus.SENDING
    db.session.commit()
    db.session.execute(
        VoiceMessage.__table__.update()
        .where(VoiceMessage.id == msg.id)
        .values(updated_at=utcnow() - timedelta(hours=1))
    )
    db.session.commit()
    assert voice_messages.send_voice_message_email_job(msg.id, True) == "sent"


def test_retry_unsent_emails_picks_old_pending(app, client, call, sent_emails):
    record(client)
    msg = message()
    msg.created_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    assert voice_messages.retry_unsent_emails() == 1
    assert len(sent_emails) == 1


def test_external_transcription_job(app, client, call, sent_emails, monkeypatch):
    import transcription_service

    monkeypatch.setattr(voice_messages.Config, "TRANSCRIPTION_SERVICE", "deepgram")
    monkeypatch.setattr(
        transcription_service, "transcribe_with_external_service", lambda **kw: "Deepgram Text"
    )
    record(client)
    recording_status(client)  # queues the transcription job (sync in tests)
    transcription(client, text="twilio text")  # must not override or send

    assert len(sent_emails) == 1
    assert sent_emails[0]["transcription_text"] == "Deepgram Text"
    assert message().transcription_source == "deepgram"


def test_unsigned_recording_callback_rejected(client, call):
    resp = client.post("/webhook/transcription", data={"CallSid": CALL_SID})
    assert resp.status_code == 403


def test_call_detail_shows_voice_message(app, client, call, sent_emails):
    from tests.conftest import login

    record(client)
    transcription(client)
    login(client, "operator")
    html = client.get(f"/calls/{call.id}").get_data(as_text=True)
    assert "Voice Messages" in html
    assert "Hallo, wo ist meine Lieferung?" in html
    assert ">sent<" in html
