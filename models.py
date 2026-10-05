#!/usr/bin/env python3
"""
Database Models for Voice Assistant
"""
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timezone
import enum
import secrets

db = SQLAlchemy()


def utcnow():
    """Naive UTC timestamp, matching the naive DateTime columns"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CallStatus(enum.Enum):
    """Call status enumeration"""

    PROCESSING = "Processing"
    COMPLETED = "Completed"
    PROBLEM = "Problem"
    HANDLED = "Handled"


class Call(db.Model):
    """Call record model"""

    __tablename__ = "calls"

    id = db.Column(db.Integer, primary_key=True)
    call_sid = db.Column(db.String(50), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(20), nullable=False, index=True)
    language = db.Column(db.String(5), nullable=False, default="de")
    status = db.Column(
        db.Enum(CallStatus), nullable=False, default=CallStatus.PROCESSING
    )
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=utcnow, onupdate=utcnow
    )
    # Set by purge-old-data once personal data is removed (GDPR retention)
    anonymized_at = db.Column(db.DateTime)

    # Relationships
    conversations = db.relationship(
        "Conversation", backref="call", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Call {self.call_sid}: {self.phone_number} ({self.status.value})>"


class Conversation(db.Model):
    """Conversation log model"""

    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(
        db.Integer, db.ForeignKey("calls.id"), nullable=False, index=True
    )
    step = db.Column(
        db.String(50), nullable=False
    )  # greeting, consent, order, help, etc.
    user_input = db.Column(db.Text)  # What user said
    bot_response = db.Column(db.Text)  # What bot said
    timestamp = db.Column(db.DateTime, default=utcnow, nullable=False)

    def __repr__(self):
        return f'<Conversation {self.step}: {self.user_input[:50] if self.user_input else "Bot response"}>'


LOOKUP_FOUND = "found"
LOOKUP_NOT_FOUND = "not_found"

VERIFICATION_PHONE = "phone"
VERIFICATION_POSTAL_CODE = "postal_code"
VERIFICATION_PENDING = "pending"          # postcode asked, caller never answered
VERIFICATION_FAILED = "failed"            # postcode wrong twice
VERIFICATION_NOT_POSSIBLE = "not_possible"  # no phone or postcode on the order


class Order(db.Model):
    """Order number looked up during a call"""

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(
        db.Integer, db.ForeignKey("calls.id"), nullable=False, index=True
    )
    order_number = db.Column(db.String(50), nullable=False, index=True)
    # What Lisa found in Afterbuy: LOOKUP_FOUND / LOOKUP_NOT_FOUND
    lookup_result = db.Column(db.String(20))
    # How the caller was verified: VERIFICATION_* values
    verification = db.Column(db.String(20))
    # Status set by staff (e.g. "Shipped"); empty until someone sets it
    status = db.Column(db.String(100))
    # Staff notes only
    notes = db.Column(db.Text)
    promised_delivery_date = db.Column(db.Date)  # Lisa's delivery estimate
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    # Relationship to Call
    call = db.relationship("Call", backref="orders")

    def __repr__(self):
        return f"<Order {self.order_number}: {self.status}>"


class UserRole(enum.Enum):
    """Dashboard user roles"""

    ADMIN = "admin"
    OPERATOR = "operator"


class User(UserMixin, db.Model):
    """Console user"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120))
    email = db.Column(db.String(254))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.OPERATOR)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    # Set when an admin issues a password; cleared once the user picks their own
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    # Part of the session cookie id; rotating it signs the user out everywhere
    session_token = db.Column(db.String(64), nullable=False, default=lambda: secrets.token_hex(16))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    password_changed_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)

    created_by = db.relationship("User", remote_side=[id])

    def set_password(self, password, temporary=False):
        """Store a new password and sign the user out of all other sessions"""
        self.password_hash = generate_password_hash(password)
        self.must_change_password = temporary
        self.password_changed_at = utcnow()
        self.rotate_session()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def rotate_session(self):
        self.session_token = secrets.token_hex(16)

    def get_id(self):
        # Flask-Login stores this in the session; it changes when the token rotates
        return f"{self.id}:{self.session_token}"

    @property
    def is_active(self):
        return self.is_active_user

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def display_name(self):
        return self.full_name or self.username

    @property
    def initials(self):
        parts = (self.full_name or self.username).split()
        letters = "".join(p[0] for p in parts[:2]) if len(parts) > 1 else parts[0][:2]
        return letters.upper()

    def __repr__(self):
        return f"<User {self.username} ({self.role.value})>"


class AuditEvent(db.Model):
    """Security-relevant actions in the console (who did what to whom)"""

    __tablename__ = "audit_events"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    target_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Username as typed for failed sign-ins (no account may exist)
    detail = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    actor = db.relationship("User", foreign_keys=[actor_id])
    target = db.relationship("User", foreign_keys=[target_id])


class EmailStatus(enum.Enum):
    """Delivery state of the voice message notification email"""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class VoiceMessage(db.Model):
    """One recorded voice message (one Twilio RecordingSid)"""

    __tablename__ = "voice_messages"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, db.ForeignKey("calls.id"), nullable=False, index=True)
    recording_sid = db.Column(db.String(64), unique=True, nullable=False, index=True)
    recording_url = db.Column(db.String(500))
    duration_seconds = db.Column(db.Integer, nullable=False, default=0)
    finish_method = db.Column(db.String(40))
    transcription_text = db.Column(db.Text)
    transcription_status = db.Column(db.String(20))
    transcription_source = db.Column(db.String(20))
    email_status = db.Column(
        db.Enum(EmailStatus), nullable=False, default=EmailStatus.PENDING
    )
    email_attempts = db.Column(db.Integer, nullable=False, default=0)
    email_sent_at = db.Column(db.DateTime)
    email_last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    call = db.relationship(
        "Call", backref=db.backref("voice_messages", cascade="all, delete-orphan")
    )

    def __repr__(self):
        return f"<VoiceMessage {self.recording_sid}: {self.email_status.value}>"
