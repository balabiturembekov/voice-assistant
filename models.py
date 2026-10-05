#!/usr/bin/env python3
"""
Database Models for Voice Assistant
"""
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timezone
import enum

db = SQLAlchemy()


def utcnow():
    """Naive UTC timestamp, matching the naive DateTime columns"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CallStatus(enum.Enum):
    """Call status enumeration"""

    PROCESSING = "В обработке"
    COMPLETED = "Завершен"
    PROBLEM = "Проблема"
    HANDLED = "Обработано"


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


class Order(db.Model):
    """Order tracking model"""

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(
        db.Integer, db.ForeignKey("calls.id"), nullable=False, index=True
    )
    order_number = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(100), default="In Progress")
    notes = db.Column(db.Text)
    promised_delivery_date = db.Column(db.Date)  # Дата обещанной доставки
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
    """Dashboard user"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.OPERATOR)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.is_active_user

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    def __repr__(self):
        return f"<User {self.username} ({self.role.value})>"


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
