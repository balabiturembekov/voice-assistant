#!/usr/bin/env python3
"""
Database migration script to add updated_at column to orders table
"""

import sqlite3
from datetime import datetime

def migrate_database():
    """Add updated_at column to orders table"""
    try:
        # Connect to database
        conn = sqlite3.connect('voice_assistant.db')
        cursor = conn.cursor()
        
        print("🔍 Checking current database structure...")
        
        # Check if orders table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
        if not cursor.fetchone():
            print("❌ Orders table doesn't exist. Creating new database...")
            conn.close()
            return False
        
        # Check if updated_at column already exists
        cursor.execute("PRAGMA table_info(orders)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'updated_at' in columns:
            print("✅ updated_at column already exists in orders table")
            conn.close()
            return True
        
        print("📝 Adding updated_at column to orders table...")
        
        # Add updated_at column
        cursor.execute("ALTER TABLE orders ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
        
        # Update existing records to have updated_at = created_at
        cursor.execute("UPDATE orders SET updated_at = created_at WHERE updated_at IS NULL")
        
        conn.commit()
        print("✅ Successfully added updated_at column to orders table")
        
        # Verify the change
        cursor.execute("PRAGMA table_info(orders)")
        columns = cursor.fetchall()
        print("📊 Updated orders table structure:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting database migration...")
    success = migrate_database()
    
    if success:
        print("✅ Migration completed successfully!")
    else:
        print("❌ Migration failed!")
