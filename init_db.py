#!/usr/bin/env python3
"""
Initialize Database for Voice Assistant
"""
from app import app, db
from models import Call, Conversation, Order, CallStatus

def init_database():
    """Initialize database tables"""
    with app.app_context():
        # Create all tables
        db.create_all()
        print("✅ Database tables created successfully!")
        
        # Force commit to ensure tables are created
        db.session.commit()
        
        # Verify tables exist
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"\n📊 Tables in database: {tables}")
        
        # Check orders table structure
        import sqlite3
        conn = sqlite3.connect('voice_assistant.db')
        cursor = conn.cursor()
        cursor.execute('PRAGMA table_info(orders)')
        columns = cursor.fetchall()
        print("\n📊 Orders table structure:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        conn.close()
        
        print("\n🎯 Call Status Options:")
        for status in CallStatus:
            print(f"  - {status.value}")

if __name__ == "__main__":
    init_database()
