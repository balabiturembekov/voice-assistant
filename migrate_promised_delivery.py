#!/usr/bin/env python3
"""
Database migration script to add promised_delivery_date field
"""
import sqlite3
from datetime import datetime


def migrate_database():
    """Add promised_delivery_date field to orders table"""
    try:
        # Connect to database
        conn = sqlite3.connect("instance/voice_assistant.db")
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(orders)")
        columns = [column[1] for column in cursor.fetchall()]

        if "promised_delivery_date" not in columns:
            # Add new column
            cursor.execute("ALTER TABLE orders ADD COLUMN promised_delivery_date DATE")
            print("✅ Added promised_delivery_date column to orders table")
        else:
            print("ℹ️  promised_delivery_date column already exists")

        conn.commit()
        conn.close()
        print("✅ Database migration completed successfully")

    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        if conn:
            conn.close()


if __name__ == "__main__":
    migrate_database()
