"""
Security layer: Twilio webhook signatures, dashboard login, roles, CSRF,
masking of personal data in logs.
"""
import logging
import re
from functools import wraps

from flask import abort, current_app, redirect, request, url_for
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from twilio.request_validator import RequestValidator

from models import User, db

logger = logging.getLogger(__name__)

login_manager = LoginManager()
csrf = CSRFProtect()

# Endpoints reachable without dashboard login
PUBLIC_ENDPOINTS = {"auth.login", "health_check", "static"}
WEBHOOK_PREFIX = "/webhook/"

PHONE_RE = re.compile(r"\+\d{7,15}")  # E.164, as Twilio sends them


def _mask_phone(match):
    digits = re.sub(r"\D", "", match.group(0))
    return f"***{digits[-3:]}"


class PIIMaskingFilter(logging.Filter):
    """Replace phone numbers in log messages with ***123"""

    def filter(self, record):
        message = record.getMessage()
        masked = PHONE_RE.sub(_mask_phone, message)
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


def install_log_masking():
    """Attach the masking filter to every root handler"""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, PIIMaskingFilter) for f in handler.filters):
            handler.addFilter(PIIMaskingFilter())


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def is_valid_twilio_request():
    """Check X-Twilio-Signature against the full public URL and POST params"""
    if not current_app.config.get("TWILIO_VALIDATE_REQUESTS", True):
        return True

    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN")
    if not auth_token:
        logger.error("TWILIO_AUTH_TOKEN is not set, rejecting webhook request")
        return False

    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(auth_token)
    return validator.validate(request.url, request.form, signature)


def protect_requests():
    """before_request hook: webhooks need a Twilio signature, everything else a login"""
    if request.path.startswith(WEBHOOK_PREFIX):
        if not is_valid_twilio_request():
            logger.warning(f"Rejected webhook with invalid signature: {request.path}")
            abort(403)
        return None

    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    if not current_user.is_authenticated:
        if request.path.startswith("/api/"):
            abort(401)
        return redirect(url_for("auth.login", next=request.full_path))
    return None


def admin_required(view):
    """Allow the view only for admins"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def init_security(app):
    """Wire login, CSRF and request protection into the app"""
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    csrf.init_app(app)
    app.before_request(protect_requests)

    install_log_masking()


def exempt_webhooks_from_csrf(app):
    """Twilio can't send CSRF tokens; webhooks are protected by signature instead.

    Call after all routes are registered.
    """
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith(WEBHOOK_PREFIX):
            csrf.exempt(app.view_functions[rule.endpoint])
