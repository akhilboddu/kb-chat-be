#!/usr/bin/env python3
"""
Test script to verify lead scorer updates conversations table correctly.
This script tests the enhanced lead scoring functionality.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_lead_scorer_update():
    """Test the enhanced lead scorer functionality."""
    try:
        from app.utils.lead_scorer import score_single_conversation
        from app.core.supabase_client import supabase
        
        print("🧪 Testing enhanced lead scorer functionality...")
        
        # Test with a known conversation ID
        conversation_id = "5f397169-f05f-4903-9ef9-656b7c02ed97"
        bot_id = "18eb9b0c-d283-4781-a727-6140d940db42"
        
        print(f"📝 Testing conversation: {conversation_id}")
        
        # Check conversation before scoring
        print("🔍 Checking conversation before scoring...")
        before_response = supabase.table('conversations').select('lead_score, conversation_summary').eq('id', conversation_id).execute()
        
        if before_response.data:
            before_data = before_response.data[0]
            print(f"   Before - Lead Score: {before_data.get('lead_score')}")
            print(f"   Before - Summary: {before_data.get('conversation_summary')}")
        
        # Run lead scoring
        print("🚀 Running lead scoring...")
        result = await score_single_conversation(conversation_id, bot_id)
        
        if result:
            print(f"✅ Lead scoring completed successfully!")
            print(f"   Status: {result.get('status')}")
            print(f"   Score: {result.get('score')}")
        else:
            print("❌ Lead scoring failed or returned None")
            return
        
        # Check conversation after scoring
        print("🔍 Checking conversation after scoring...")
        after_response = supabase.table('conversations').select('lead_score, conversation_summary').eq('id', conversation_id).execute()
        
        if after_response.data:
            after_data = after_response.data[0]
            print(f"   After - Lead Score: {after_data.get('lead_score')}")
            print(f"   After - Summary: {after_data.get('conversation_summary')}")
            
            # Verify the update worked
            if after_data.get('lead_score') is not None:
                print("✅ Conversation table successfully updated with lead score!")
            else:
                print("❌ Conversation table was not updated with lead score")
                
            if after_data.get('conversation_summary'):
                print("✅ Conversation table successfully updated with summary!")
            else:
                print("❌ Conversation table was not updated with summary")
        else:
            print("❌ Could not retrieve conversation after scoring")
        
        print("\n📊 Test completed!")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("This is expected if running outside the proper environment")
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🧪 Lead Scorer Update Test")
    print("=" * 50)
    asyncio.run(test_lead_scorer_update()) 