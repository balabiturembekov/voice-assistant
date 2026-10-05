from flask import Flask, request, Response, render_template
from twilio.twiml.voice_response import VoiceResponse
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
import click
import logging
import secrets
from datetime import timezone
from zoneinfo import ZoneInfo
from config import Config, missing_settings
from models import db, Call, Conversation, Order, CallStatus, User, UserRole, utcnow
from auth import auth_bp
from security import init_security, exempt_webhooks_from_csrf
from voice import apply_voice
import ui
from sqlalchemy import desc, text
from jobs_queue import get_redis
from calls import log_conversation, update_call_status
from call_flow import VOICEMAIL_MAX_LENGTH, flow_bp
from prompts import prompt
from analytics import call_outcomes, dashboard_data
from services import detect_language, send_voice_message_email
from retention import anonymize_calls_older_than
from voice_messages import (
    queue_email,
    queue_external_transcription,
    retry_unsent_emails,
    set_transcription,
    upsert_voice_message,
    uses_external_transcription,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
# nginx sets X-Forwarded-For/Proto; needed for the real client IP and for the
# https:// URL that Twilio signs
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

_missing = missing_settings()
if _missing:
    if not Config.FLASK_DEBUG:
        raise RuntimeError(f"Missing required settings: {', '.join(_missing)}")
    logger.warning(f"Missing settings (ignored in debug): {', '.join(_missing)}")
if not app.config.get("SECRET_KEY"):
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["REMEMBER_COOKIE_SECURE"] = False

# Initialize database (schema is managed by Alembic: flask db upgrade)
db.init_app(app)
migrate = Migrate(app, db)
init_security(app)
app.register_blueprint(auth_bp)
app.register_blueprint(flow_bp)
app.after_request(apply_voice)
ui.register(app)


@app.template_filter("local_time")
def local_time(value, fmt="%d.%m.%Y %H:%M"):
    """Naive UTC timestamp from the DB -> office time zone"""
    if value is None:
        return "—"
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(Config.TIMEZONE)).strftime(fmt)


@app.route("/health", methods=["GET"])
def health_check():
    """Liveness plus dependency checks (database, Redis)"""
    checks = {}
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Health check: database error: {e}")
        checks["database"] = "error"
        db.session.rollback()
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        logger.error(f"Health check: redis error: {e}")
        checks["redis"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    return {"status": "healthy" if healthy else "unhealthy", "checks": checks}, (
        200 if healthy else 503
    )


@app.route("/", methods=["GET"])
def dashboard():
    """Console overview"""
    return render_template("dashboard.html", **dashboard_data())


@app.route("/calls", methods=["GET"])
def calls():
    """Calls list page with filtering"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    language_filter = request.args.get("language")
    phone_filter = request.args.get("phone")
    
    # Build query
    query = Call.query
    
    if status_filter in CallStatus.__members__:
        query = query.filter(Call.status == CallStatus[status_filter])
    
    if language_filter:
        query = query.filter(Call.language == language_filter)
    
    if phone_filter:
        query = query.filter(Call.phone_number.contains(phone_filter))
    
    # Paginate results
    calls = query.order_by(desc(Call.created_at)).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template(
        "calls.html", calls=calls, outcomes=call_outcomes([c.id for c in calls.items])
    )


@app.route("/calls/<int:call_id>", methods=["GET"])
def call_detail(call_id):
    """Call detail page"""
    call = db.get_or_404(Call, call_id)
    conversations = (
        Conversation.query.filter_by(call_id=call_id)
        .order_by(Conversation.timestamp)
        .all()
    )
    orders = Order.query.filter_by(call_id=call_id).all()
    
    return render_template(
        "call_detail.html",
        call=call,
        conversations=conversations,
        orders=orders,
        outcome=call_outcomes([call.id])[call.id],
    )


@app.route("/api/calls/<int:call_id>/status", methods=["POST"])
def update_call_status_api(call_id):
    """Update call status via API"""
    try:
        data = request.get_json(silent=True) or {}
        new_status = data.get("status")
        
        if not new_status or new_status not in [status.name for status in CallStatus]:
            return {"error": "Invalid status"}, 400
        
        call = db.get_or_404(Call, call_id)
        call.status = CallStatus[new_status]
        try:
            db.session.commit()
            logger.info(f"Call {call_id} status updated to {new_status}")
            return {"message": "Status updated successfully", "status": new_status}
        except Exception as db_error:
            logger.error(f"Database error updating call status: {db_error}")
            db.session.rollback()
            return {"error": "Failed to update status"}, 500
        
    except Exception as e:
        logger.error(f"Error updating call status: {e}")
        return {"error": "Failed to update status"}, 500


@app.route("/api/orders/<int:order_id>/status", methods=["POST"])
def update_order_status_api(order_id):
    """Update order status via API"""
    try:
        data = request.get_json(silent=True) or {}
        new_status = data.get("status")
        notes = data.get("notes", "")
        
        if not new_status:
            return {"error": "Status is required"}, 400
        
        order = db.get_or_404(Order, order_id)
        order.status = new_status
        if notes:
            order.notes = notes
        # Update updated_at timestamp
        order.updated_at = utcnow()
        try:
            db.session.commit()
            logger.info(f"Order {order_id} status updated to {new_status}")
            return {
                "message": "Order status updated successfully",
                "status": new_status,
            }
        except Exception as db_error:
            logger.error(f"Database error updating order status: {db_error}")
            db.session.rollback()
            return {"error": "Failed to update order status"}, 500
        
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        return {"error": "Failed to update order status"}, 500


@app.route("/orders", methods=["GET"])
def orders():
    """Orders list page with filtering"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    phone_filter = request.args.get("phone")
    order_number_filter = request.args.get("order_number")
    
    # Build query
    query = Order.query.join(Call)
    
    if status_filter:
        query = query.filter(Order.status == status_filter)
    
    if phone_filter:
        query = query.filter(Call.phone_number.contains(phone_filter))
    
    if order_number_filter:
        query = query.filter(Order.order_number.contains(order_number_filter))
    
    # Paginate results
    orders = query.order_by(desc(Order.created_at)).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template("orders.html", orders=orders, statuses=order_statuses())


@app.route("/orders/<int:order_id>", methods=["GET"])
def order_detail(order_id):
    """Order detail page"""
    order = db.get_or_404(Order, order_id)
    return render_template("order_detail.html", order=order, statuses=order_statuses())


def order_statuses():
    """Distinct order statuses in use, for filters and suggestions"""
    return [
        row[0] for row in db.session.query(Order.status).distinct().order_by(Order.status) if row[0]
    ]


@app.route("/webhook/recorded", methods=["POST"])
def handle_recorded():
    """<Record> action: store the recording and thank the caller"""
    recording_url = request.form.get("RecordingUrl", "")
    recording_sid = request.form.get("RecordingSid", "")
    digits = request.form.get("Digits", "")
    caller_number = request.form.get("From", "")
    call_sid = request.form.get("CallSid", "")
    try:
        duration_seconds = int(request.form.get("RecordingDuration") or 0)
    except ValueError:
        duration_seconds = 0

    if digits == "#":
        finish_method = "user_pressed_hash"
    elif duration_seconds >= VOICEMAIL_MAX_LENGTH:
        finish_method = "max_length_reached"
    elif duration_seconds > 0:
        finish_method = "timeout_silence"
    else:
        finish_method = "unknown"

    logger.info(
        f"Voice message recorded for call {call_sid}: {duration_seconds}s, finished by {finish_method}"
    )

    call = Call.query.filter_by(call_sid=call_sid).first()
    language = (
        call.language if call and call.language else detect_language(caller_number)
    )
    recorded_ok = duration_seconds >= 1 and bool(recording_url)

    thank_you = prompt(language, "voicemail_thanks" if recorded_ok else "voicemail_failed")

    if call:
        try:
            if recorded_ok and recording_sid:
                upsert_voice_message(
                    call,
                    recording_sid,
                    recording_url=recording_url,
                    duration_seconds=duration_seconds,
                    finish_method=finish_method,
                )
            log_conversation(
                call.id,
                "voice_message_recorded" if recorded_ok else "voice_message_failed",
                user_input=f"Voice message ({duration_seconds}s, finished by {finish_method})",
                bot_response=thank_you,
            )
            update_call_status(call.id, CallStatus.COMPLETED)
        except Exception as e:
            logger.error(f"Error storing voice message for call {call_sid}: {e}", exc_info=True)
            db.session.rollback()
    else:
        logger.warning(f"Call record not found for {call_sid} in handle_recorded")

    response = VoiceResponse()
    response.say(
        thank_you if call else prompt(language, "goodbye"),
    )
    response.hangup()
    return Response(str(response), mimetype="text/xml")


@app.route("/webhook/recording_status", methods=["POST"])
def handle_recording_status():
    """recordingStatusCallback: the recording file is ready"""
    recording_url = request.form.get("RecordingUrl", "")
    recording_sid = request.form.get("RecordingSid", "")
    recording_status = request.form.get("RecordingStatus", "")
    call_sid = request.form.get("CallSid", "")
    logger.info(f"Recording {recording_sid} status: {recording_status}")

    if recording_status != "completed" or not recording_url or not recording_sid:
        return Response(status=200)

    call = Call.query.filter_by(call_sid=call_sid).first()
    if not call:
        logger.warning(f"Call record not found for {call_sid} in handle_recording_status")
        return Response(status=200)

    try:
        duration = request.form.get("RecordingDuration")
        message = upsert_voice_message(
            call,
            recording_sid,
            recording_url=recording_url,
            duration_seconds=int(duration) if duration and duration.isdigit() else None,
        )
    except Exception as e:
        logger.error(f"Error storing recording {recording_sid}: {e}", exc_info=True)
        db.session.rollback()
        return Response(status=500)

    if uses_external_transcription():
        queue_external_transcription(message.id)
    # Send without transcription if it never arrives
    queue_email(
        message.id,
        allow_without_transcription=True,
        delay_seconds=Config.VOICE_EMAIL_FALLBACK_DELAY,
    )
    return Response(status=200)


@app.route("/webhook/transcription", methods=["POST"])
def handle_transcription():
    """transcribeCallback from Twilio's built-in transcription"""
    transcription_text = request.form.get("TranscriptionText", "")
    transcription_status = request.form.get("TranscriptionStatus", "")
    recording_sid = request.form.get("RecordingSid", "")
    recording_url = request.form.get("RecordingUrl", "")
    call_sid = request.form.get("CallSid", "")
    logger.info(
        f"Transcription for {recording_sid}: status={transcription_status}, length={len(transcription_text)}"
    )

    call = Call.query.filter_by(call_sid=call_sid).first()
    if not call or not recording_sid:
        logger.warning(f"Call record not found for {call_sid} in handle_transcription")
        return Response(status=200)

    try:
        message = upsert_voice_message(call, recording_sid, recording_url=recording_url)
        set_transcription(message, transcription_text, transcription_status, "twilio")
    except Exception as e:
        logger.error(f"Error storing transcription for {recording_sid}: {e}", exc_info=True)
        db.session.rollback()
        return Response(status=500)

    if not uses_external_transcription():
        # A failed transcription still means "nothing better is coming"
        queue_email(message.id, allow_without_transcription=True)
    return Response(status=200)


@app.route("/api/health", methods=["GET"])
def api_health():
    """API health check"""
    return {
        "message": "Voice Assistant with Database",
        "endpoints": {
            "webhook": "/webhook/voice",
            "health": "/api/health",
            "dashboard": "/",
        },
    }


exempt_webhooks_from_csrf(app)


@app.cli.command("create-user")
@click.argument("username")
@click.option("--role", type=click.Choice(["admin", "operator"]), default="operator")
@click.password_option()
def create_user_command(username, role, password):
    """Create a dashboard user: flask --app app create-user NAME --role admin"""
    if User.query.filter_by(username=username).first():
        raise click.ClickException(f"User {username} already exists")
    user = User(username=username, role=UserRole(role))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created {role} user {username}")


@app.cli.command("send-test-email")
def send_test_email_command():
    """Send a test voice-message email to MAIL_RECIPIENT"""
    ok = send_voice_message_email(
        caller_number="+499876543210",
        recording_url="https://api.twilio.com/2010-04-01/Accounts/ACxxxxx/Recordings/RE987654321",
        transcription_text="Test message from send-test-email",
        duration_seconds=10,
        language="de",
        order_number="TEST12345",
    )
    if not ok:
        raise click.ClickException("Email sending failed, see logs")
    click.echo(f"Test email sent to {Config.MAIL_RECIPIENT}")


@app.cli.command("retry-unsent-emails")
def retry_unsent_emails_command():
    """Re-queue voice message emails stuck in pending/failed (run from cron)"""
    count = retry_unsent_emails()
    click.echo(f"Re-queued {count} voice message email(s)")


@app.cli.command("purge-old-data")
@click.option("--days", type=int, default=None, help="Defaults to DATA_RETENTION_DAYS")
def purge_old_data_command(days):
    """GDPR: anonymize calls older than N days (phone, dialog texts, recordings)"""
    days = days or Config.DATA_RETENTION_DAYS
    if not days:
        raise click.ClickException("Set DATA_RETENTION_DAYS or pass --days")
    count = anonymize_calls_older_than(days)
    click.echo(f"Anonymized {count} call(s) older than {days} days")


if __name__ == "__main__":
    app.run(debug=Config.FLASK_DEBUG, host="0.0.0.0", port=5001)
