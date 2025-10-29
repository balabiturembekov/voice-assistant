#!/usr/bin/env python3
"""
Database Models for Voice Assistant
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import enum

db = SQLAlchemy()


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

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
    call_id = db.Column(db.Integer, db.ForeignKey("calls.id"), nullable=False)
    step = db.Column(
        db.String(50), nullable=False
    )  # greeting, consent, order, help, etc.
    user_input = db.Column(db.Text)  # What user said
    bot_response = db.Column(db.Text)  # What bot said
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Conversation {self.step}: {self.user_input[:50] if self.user_input else "Bot response"}>'


class Order(db.Model):
    """Order tracking model"""

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.Integer, db.ForeignKey("calls.id"), nullable=False)
    order_number = db.Column(db.String(50), nullable=False, index=True)
    status = db.Column(db.String(100), default="In Progress")
    notes = db.Column(db.Text)
    promised_delivery_date = db.Column(db.Date)  # Дата обещанной доставки
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationship to Call
    call = db.relationship("Call", backref="orders")

    def __repr__(self):
        return f"<Order {self.order_number}: {self.status}>"
