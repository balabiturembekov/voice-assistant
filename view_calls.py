#!/usr/bin/env python3
"""
View Call Data from Database
"""
from app import app, db
from models import Call, Conversation, Order, CallStatus
from datetime import datetime

def view_calls():
    """View all calls in database"""
    with app.app_context():
        calls = Call.query.order_by(Call.created_at.desc()).all()
        
        print("📞 Voice Assistant Call Log")
        print("=" * 50)
        
        if not calls:
            print("No calls found in database.")
            return
        
        for call in calls:
            print(f"\n📞 Call ID: {call.id}")
            print(f"   📱 Phone: {call.phone_number}")
            print(f"   🆔 Call SID: {call.call_sid}")
            print(f"   🌍 Language: {call.language}")
            print(f"   📊 Status: {call.status.value}")
            print(f"   📅 Created: {call.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   🔄 Updated: {call.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Show conversations
            conversations = Conversation.query.filter_by(call_id=call.id).order_by(Conversation.timestamp).all()
            if conversations:
                print(f"   💬 Conversations ({len(conversations)}):")
                for conv in conversations:
                    print(f"      - {conv.step}: {conv.user_input or conv.bot_response}")
            
            # Show orders
            orders = Order.query.filter_by(call_id=call.id).all()
            if orders:
                print(f"   📦 Orders ({len(orders)}):")
                for order in orders:
                    print(f"      - {order.order_number}: {order.status}")

def view_stats():
    """View call statistics"""
    with app.app_context():
        total_calls = Call.query.count()
        status_counts = {}
        
        for status in CallStatus:
            count = Call.query.filter_by(status=status).count()
            status_counts[status.value] = count
        
        print("\n📊 Call Statistics")
        print("=" * 30)
        print(f"Total Calls: {total_calls}")
        for status, count in status_counts.items():
            print(f"{status}: {count}")

if __name__ == "__main__":
    view_calls()
    view_stats()
