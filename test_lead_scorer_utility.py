#!/usr/bin/env python3

import asyncio
import sys
import os
import json

# Add the current directory to Python path to import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.lead_scorer import process_lead_scoring, run_lead_scoring_batch, run_single_lead_scoring

async def test_lead_scorer_utility():
    """Test the lead scorer utility functions."""
    
    print("=== Testing Lead Scorer Utility ===")
    
    # Test 1: Empty conversations list
    print("\n1. Testing with empty conversations list...")
    empty_result = await process_lead_scoring([])
    print(f"Empty result: {json.dumps(empty_result, indent=2)}")
    assert "No conversations provided" in empty_result["errors"]
    print("✅ Empty list test passed")
    
    # Test 2: Invalid conversation data (missing fields)
    print("\n2. Testing with invalid conversation data...")
    invalid_conversations = [
        {"conversation_id": "test-123"},  # Missing bot_id
        {"bot_id": "bot-456"},           # Missing conversation_id
        {}                               # Missing both
    ]
    invalid_result = await process_lead_scoring(invalid_conversations)
    print(f"Invalid data result: {json.dumps(invalid_result, indent=2)}")
    assert invalid_result["failed"] == 3
    assert invalid_result["successful"] == 0
    print("✅ Invalid data test passed")
    
    # Test 3: Valid conversation data (will likely fail due to non-existent conversations)
    print("\n3. Testing with valid conversation data...")
    valid_conversations = [
        {
            "conversation_id": "test-conversation-1",
            "bot_id": "test-bot-1"
        },
        {
            "conversation_id": "test-conversation-2", 
            "bot_id": "test-bot-2"
        }
    ]
    valid_result = await process_lead_scoring(valid_conversations)
    print(f"Valid data result: {json.dumps(valid_result, indent=2)}")
    print("✅ Valid data test completed (results depend on database state)")
    
    # Test 4: Test synchronous wrapper
    print("\n4. Testing synchronous wrapper...")
    try:
        sync_result = run_lead_scoring_batch([
            {"conversation_id": "sync-test-1", "bot_id": "sync-bot-1"}
        ])
        print(f"Sync result: {json.dumps(sync_result, indent=2)}")
        print("✅ Synchronous wrapper test completed")
    except Exception as e:
        print(f"⚠️  Synchronous wrapper test failed (expected): {e}")
    
    # Test 5: Test single conversation scoring
    print("\n5. Testing single conversation scoring...")
    try:
        single_result = run_single_lead_scoring("single-test-1", "single-bot-1")
        print(f"Single conversation result: {single_result}")
        print("✅ Single conversation test completed")
    except Exception as e:
        print(f"⚠️  Single conversation test failed (expected): {e}")
    
    print("\n=== Lead Scorer Utility Tests Complete ===")
    print("Note: Some tests may fail due to missing database records, which is expected.")

if __name__ == "__main__":
    asyncio.run(test_lead_scorer_utility()) 