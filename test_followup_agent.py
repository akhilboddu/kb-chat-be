#!/usr/bin/env python3

import asyncio
import os
import sys

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.follow_up_email_agent import generate_follow_up_email

async def test_followup_agent():
    """Test the improved follow-up email agent"""
    
    # Test with a real conversation ID from your logs
    test_bot_id = "18eb9b0c-d283-4781-a727-6140d940db42"
    test_conversation_id = "85a2932e-4ecf-41de-994a-72ecd294c26e"  # From your logs
    
    print(f"Testing follow-up email agent...")
    print(f"Bot ID: {test_bot_id}")
    print(f"Conversation ID: {test_conversation_id}")
    
    result = await generate_follow_up_email(
        bot_id=test_bot_id,
        conversation_id=test_conversation_id,
        previous_email_context="Hi Asif, I wanted to follow up on our conversation and see if you have any questions or need additional information. Best regards, Lola",
        custom_instructions="Create a personalized follow-up email that shows genuine interest in the customer's needs and provides additional value."
    )
    
    if result:
        print("\n✅ SUCCESS: Follow-up email generated")
        print(f"Subject: {result.get('subject', 'N/A')}")
        print(f"Email body: {result.get('email_body', 'N/A')[:200]}...")
        print(f"Key points: {result.get('key_points', [])}")
        print(f"Urgency level: {result.get('urgency_level', 'N/A')}")
    else:
        print("\n❌ FAILED: Follow-up email generation failed")

if __name__ == "__main__":
    asyncio.run(test_followup_agent()) 