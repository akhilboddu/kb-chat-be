#!/usr/bin/env python3
"""
Test script to verify human response endpoints work correctly with conversation_id
"""

import asyncio
import httpx
import sys
import os
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Base URL for the API (adjust as needed)
BASE_URL = "http://localhost:8000/api"

async def test_human_response_endpoints():
    """Test the updated human response endpoints"""
    
    async with httpx.AsyncClient() as client:
        print("\n" + "="*60)
        print("TESTING HUMAN RESPONSE ENDPOINTS WITH CONVERSATION_ID")
        print("="*60)
        
        # Test conversation IDs (replace with actual IDs from your database)
        test_conversation_id = "test_conv_123"  # You'll need to use a real conversation ID
        
        # Test 1: Human Response Endpoint
        print("\n1. Testing POST /conversations/human_response")
        try:
            response = await client.post(
                f"{BASE_URL}/conversations/human_response",
                json={
                    "conversation_id": test_conversation_id,
                    "human_response": "This is a test human response",
                    "update_kb": False
                }
            )
            if response.status_code == 200:
                print("✅ Human response endpoint working correctly")
                print(f"   Response: {response.json()}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        # Test 2: Human Chat Endpoint
        print("\n2. Testing POST /conversations/human-chat")
        try:
            response = await client.post(
                f"{BASE_URL}/conversations/human-chat",
                json={
                    "conversation_id": test_conversation_id,
                    "message": "This is a test human chat message"
                }
            )
            if response.status_code == 200:
                print("✅ Human chat endpoint working correctly")
                print(f"   Response: {response.json()}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        # Test 3: Get History Endpoint
        print(f"\n3. Testing GET /conversations/{test_conversation_id}/history")
        try:
            response = await client.get(
                f"{BASE_URL}/conversations/{test_conversation_id}/history"
            )
            if response.status_code == 200:
                print("✅ Get history endpoint working correctly")
                data = response.json()
                print(f"   Conversation ID: {data.get('conversation_id')}")
                print(f"   Message count: {len(data.get('history', []))}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        # Test 4: List Conversations Endpoint
        print("\n4. Testing GET /conversations")
        try:
            response = await client.get(f"{BASE_URL}/conversations")
            if response.status_code == 200:
                print("✅ List conversations endpoint working correctly")
                data = response.json()
                print(f"   Total KB groups: {len(data.get('conversations', []))}")
                for kb_group in data.get('conversations', [])[:3]:  # Show first 3
                    print(f"   - KB: {kb_group.get('name')} (ID: {kb_group.get('kb_id')})")
                    conv = kb_group.get('conversation', {})
                    print(f"     Messages: {conv.get('message_count')}, Needs attention: {conv.get('needs_human_attention')}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        # Test 5: Human Response with KB Update
        print("\n5. Testing Human Response with KB Update")
        try:
            response = await client.post(
                f"{BASE_URL}/conversations/human_response",
                json={
                    "conversation_id": test_conversation_id,
                    "human_response": "The product costs $99",
                    "update_kb": True,
                    "kb_update_text": "Our premium product is priced at $99"
                }
            )
            if response.status_code == 200:
                print("✅ Human response with KB update working correctly")
                print(f"   Response: {response.json()}")
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        print("\n" + "="*60)
        print("TEST COMPLETE")
        print("="*60)
        print("\nNOTE: Make sure to use real conversation IDs from your database")
        print("You can find them by querying: SELECT id FROM conversations LIMIT 5;")

if __name__ == "__main__":
    print("\nStarting Human Response Endpoints Test...")
    print("Make sure your backend server is running on localhost:8000")
    asyncio.run(test_human_response_endpoints()) 