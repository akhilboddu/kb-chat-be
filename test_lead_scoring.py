#!/usr/bin/env python3

import asyncio
import sys
import os

# Add the current directory to Python path to import app modules
sys.path.insert(0, os.getcwd())

async def test_lead_scoring():
    from app.utils.lead_scorer import score_single_conversation
    
    conversation_id = 'e2df092c-6726-4e14-aead-35d4f8e711ae'
    bot_id = '18eb9b0c-d283-4781-a727-6140d940db42'
    
    print(f'🧪 Testing lead scoring for conversation: {conversation_id}')
    print(f'   Bot ID: {bot_id}')
    
    try:
        result = await score_single_conversation(conversation_id, bot_id)
        print(f'✅ Result: {result}')
        return True
    except Exception as e:
        print(f'❌ Error: {str(e)}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_lead_scoring())
    print(f"\n🎯 Test {'PASSED' if success else 'FAILED'}") 