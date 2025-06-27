#!/usr/bin/env python3
"""
Test script for Deepgram Voice Agent SDK implementation
Run this to verify the backend is working correctly
"""

import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()

async def test_voice_agent_connection():
    """Test the Voice Agent WebSocket connection"""
    
    # Test bot ID
    bot_id = "test_bot"
    
    # WebSocket URL
    ws_url = f"ws://localhost:8000/ws/voice-agent-sdk/{bot_id}"
    
    print(f"🧪 Testing Voice Agent connection to: {ws_url}")
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("✅ WebSocket connection established")
            
            # Wait for initial messages
            for i in range(5):  # Wait for up to 5 messages
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(message)
                    print(f"📨 Received: {data.get('type', 'unknown')} - {data.get('message', data.get('status', 'no message'))}")
                    
                    if data.get('type') == 'settings_applied':
                        print("🎉 Voice Agent is ready!")
                        break
                        
                except asyncio.TimeoutError:
                    print("⏱️ Waiting for more messages...")
                    break
                except json.JSONDecodeError:
                    print(f"📨 Received non-JSON message: {message[:100]}...")
            
            # Send a test control message
            control_msg = {
                "type": "control",
                "action": "disconnect"
            }
            await websocket.send(json.dumps(control_msg))
            print("📤 Sent disconnect message")
            
            print("✅ Test completed successfully!")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return True

async def check_environment():
    """Check if required environment variables are set"""
    print("🔍 Checking environment variables...")
    
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not deepgram_key:
        print("❌ DEEPGRAM_API_KEY not set")
        return False
    else:
        print(f"✅ DEEPGRAM_API_KEY set (length: {len(deepgram_key)})")
    
    if not openai_key:
        print("⚠️ OPENAI_API_KEY not set (will use default)")
    else:
        print(f"✅ OPENAI_API_KEY set (length: {len(openai_key)})")
    
    return True

async def main():
    """Main test function"""
    print("🎤 Deepgram Voice Agent Test")
    print("=" * 40)
    
    # Check environment
    if not await check_environment():
        print("❌ Environment check failed")
        return
    
    print("\n🔌 Testing WebSocket connection...")
    success = await test_voice_agent_connection()
    
    if success:
        print("\n🎉 All tests passed!")
        print("\nNext steps:")
        print("1. Start your FastAPI server: python -m uvicorn app.main:app --reload")
        print("2. Open your frontend and test the voice conversation")
        print("3. Check the logs for any issues")
    else:
        print("\n❌ Tests failed. Check your configuration and try again.")

if __name__ == "__main__":
    asyncio.run(main()) 