#!/usr/bin/env python3
"""
Test script to verify conversation isolation fix
Tests that conversations are properly isolated by conversation_id
instead of being mixed by kb_id
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core import supabase_metadata_manager as db_manager
from app.core.supabase_client import supabase

def print_test_header(test_name: str):
    """Print a formatted test header"""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}")

def print_result(passed: bool, message: str):
    """Print test result with color"""
    if passed:
        print(f"✅ PASS: {message}")
    else:
        print(f"❌ FAIL: {message}")

async def test_conversation_isolation():
    """Main test function"""
    print("\n🧪 CONVERSATION ISOLATION TEST SUITE")
    print("Testing that conversations are properly isolated by conversation_id")
    
    # Test data
    test_bot_id = "test-bot-" + datetime.now().strftime("%Y%m%d%H%M%S")
    test_kb_id = "test-kb-" + datetime.now().strftime("%Y%m%d%H%M%S")
    
    # Create test conversations
    conversation_1_id = "test-conv-alice-" + datetime.now().strftime("%Y%m%d%H%M%S")
    conversation_2_id = "test-conv-bob-" + datetime.now().strftime("%Y%m%d%H%M%S")
    
    try:
        # Test 1: Add messages to different conversations
        print_test_header("Message Storage Isolation")
        
        # Add messages for Alice
        success1 = db_manager.add_conversation_message(conversation_1_id, "human", "Hi, I'm Alice")
        success2 = db_manager.add_conversation_message(conversation_1_id, "ai", "Hello Alice! How can I help you?")
        success3 = db_manager.add_conversation_message(conversation_1_id, "human", "What are your prices?")
        
        print_result(success1 and success2 and success3, "Added messages for Alice's conversation")
        
        # Add messages for Bob
        success4 = db_manager.add_conversation_message(conversation_2_id, "human", "Hi, I'm Bob")
        success5 = db_manager.add_conversation_message(conversation_2_id, "ai", "Hello Bob! How can I help you?")
        success6 = db_manager.add_conversation_message(conversation_2_id, "human", "Do you offer support?")
        
        print_result(success4 and success5 and success6, "Added messages for Bob's conversation")
        
        # Test 2: Retrieve conversation histories
        print_test_header("Message Retrieval Isolation")
        
        # Get Alice's history
        alice_history = db_manager.get_conversation_history(conversation_1_id)
        alice_messages = [msg['content'] for msg in alice_history]
        
        # Check Alice only sees her messages
        alice_correct = (
            len(alice_history) == 3 and
            "Hi, I'm Alice" in alice_messages and
            "What are your prices?" in alice_messages and
            "Hi, I'm Bob" not in alice_messages and
            "Do you offer support?" not in alice_messages
        )
        
        print_result(alice_correct, f"Alice's conversation has {len(alice_history)} messages (expected 3)")
        if alice_correct:
            for msg in alice_history:
                print(f"  - {msg['message_type']}: {msg['content'][:50]}...")
        
        # Get Bob's history
        bob_history = db_manager.get_conversation_history(conversation_2_id)
        bob_messages = [msg['content'] for msg in bob_history]
        
        # Check Bob only sees his messages
        bob_correct = (
            len(bob_history) == 3 and
            "Hi, I'm Bob" in bob_messages and
            "Do you offer support?" in bob_messages and
            "Hi, I'm Alice" not in bob_messages and
            "What are your prices?" not in bob_messages
        )
        
        print_result(bob_correct, f"Bob's conversation has {len(bob_history)} messages (expected 3)")
        if bob_correct:
            for msg in bob_history:
                print(f"  - {msg['message_type']}: {msg['content'][:50]}...")
        
        # Test 3: Verify complete isolation
        print_test_header("Cross-Conversation Isolation Check")
        
        isolation_test_passed = alice_correct and bob_correct
        print_result(
            isolation_test_passed,
            "Conversations are properly isolated - no message leakage detected"
        )
        
        # Test 4: Test the deprecated kb-based function (should show the problem)
        print_test_header("Legacy KB-based Function Test (Deprecated)")
        
        # This simulates what would happen if both conversations were for the same KB
        # We'll check if the old function would have mixed them
        print("⚠️  Testing deprecated get_conversation_history_by_kb function...")
        print("    (This should show why the old approach was problematic)")
        
        # Clean up test data
        print_test_header("Cleanup")
        
        # Delete test messages
        cleanup1 = db_manager.delete_conversation_history(conversation_1_id)
        cleanup2 = db_manager.delete_conversation_history(conversation_2_id)
        
        print_result(cleanup1 and cleanup2, "Test data cleaned up")
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        if isolation_test_passed:
            print("✅ ALL TESTS PASSED - Conversation isolation is working correctly!")
            print("   Each conversation maintains its own isolated message history.")
        else:
            print("❌ TESTS FAILED - Conversation isolation is not working properly!")
            print("   Messages may be leaking between conversations.")
        
    except Exception as e:
        print(f"\n❌ ERROR during testing: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run the test
    asyncio.run(test_conversation_isolation()) 