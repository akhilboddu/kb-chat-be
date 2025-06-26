from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, Optional
import asyncio
import json
import base64
import time
import os
from dotenv import load_dotenv
import logging
import websockets
import ssl

from app.core import agent_manager
from app.core.supabase_kb_manager import KBManager
from app.utils.cache_utils import get_cached_response, set_cached_response

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-agent"])

class DeepgramVoiceAgentSession:
    """Manages a Deepgram Voice Agent session"""
    
    def __init__(self, bot_id: str, websocket: WebSocket):
        self.bot_id = bot_id
        self.websocket = websocket
        self.session_id = f"voice_agent_{bot_id}_{int(time.time())}"
        
        # API Configuration
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        
        # State management
        self.is_connected = True
        self.deepgram_ws = None
        self.audio_queue = asyncio.Queue()
        self.is_processing = False
        
        # Performance tracking
        self.metrics = {
            "total_latency": []
        }
        
    async def initialize(self):
        """Initialize Deepgram Voice Agent connection"""
        try:
            logger.info(f"🎙️ Initializing Deepgram Voice Agent for bot {self.bot_id}")
            
            # Validate API keys
            if not self.deepgram_key:
                raise ValueError("❌ Deepgram API key is missing")
            if not self.openai_key:
                logger.warning("⚠️ OpenAI API key is missing - will use default LLM")
            
            # Connect to Deepgram Voice Agent API
            await self.connect_to_deepgram()
            
            # Send service status to frontend
            await self.safe_send_json({
                "type": "service_status",
                "deepgram_voice_agent": True,
                "status": "connected"
            })
            
            # Send capabilities to frontend
            await self.safe_send_json({
                "type": "initialized",
                "capabilities": {
                    "voice_agent": True,
                    "real_time_conversation": True
                }
            })
            
            logger.info("🎉 Deepgram Voice Agent initialization completed")
            
        except Exception as e:
            logger.error(f"❌ Voice Agent initialization failed: {e}")
            await self.safe_send_json({
                "type": "error",
                "message": f"Voice Agent initialization failed: {str(e)}"
            })
            raise

    async def connect_to_deepgram(self):
        """Connect to Deepgram Voice Agent API"""
        try:
            # Get bot configuration for custom prompt
            bot_data = await self.get_bot_data()
            custom_prompt = bot_data.get("custom_prompt") or "You are a helpful AI assistant focused on customer service."
            
            # Connect to Deepgram Voice Agent API
            uri = "wss://agent.deepgram.com/v1/agent/converse"
            
            # Use subprotocols for authentication as per documentation
            self.deepgram_ws = await websockets.connect(
                uri,
                subprotocols=["token", self.deepgram_key]
            )
            
            logger.info("✅ Connected to Deepgram Voice Agent API")
            
            # Send configuration message
            config_message = {
                "type": "Settings",
                "audio": {
                    "input": {
                        "encoding": "linear16",
                        "sample_rate": 16000,
                    },
                    "output": {
                        "encoding": "linear16",
                        "sample_rate": 24000,
                        "container": "wav",
                    },
                },
                "agent": {
                    "language": "en",
                    "listen": {
                        "provider": {
                            "type": "deepgram",
                            "model": "nova-3",
                        }
                    },
                    "think": {
                        "provider": {
                            "type": "open_ai",
                            "model": "gpt-4o-mini",
                            "temperature": 0.7
                        },
                        "prompt": custom_prompt
                    },
                    "speak": {
                        "provider": {
                            "type": "deepgram",
                            "model": "aura-2-thalia-en"
                        }
                    }
                }
            }
            
            await self.deepgram_ws.send(json.dumps(config_message))
            logger.info("📤 Sent configuration to Deepgram Voice Agent")
            
            # No need to send StartConversation - not part of the API
            
            # Start listening for messages from Deepgram
            asyncio.create_task(self.listen_to_deepgram())
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Deepgram Voice Agent: {e}")
            raise

    async def listen_to_deepgram(self):
        """Listen for messages from Deepgram Voice Agent"""
        try:
            async for message in self.deepgram_ws:
                if not self.is_connected:
                    break
                    
                try:
                    if isinstance(message, str):
                        # Text message (JSON)
                        data = json.loads(message)
                        await self.handle_deepgram_message(data)
                    else:
                        # Binary message (audio data)
                        await self.handle_deepgram_audio(message)
                        
                except Exception as e:
                    logger.error(f"❌ Error processing Deepgram message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("🔌 Deepgram Voice Agent connection closed")
        except Exception as e:
            logger.error(f"❌ Error in Deepgram listener: {e}")

    async def handle_deepgram_message(self, data: dict):
        """Handle text messages from Deepgram Voice Agent"""
        message_type = data.get("type")
        
        logger.info(f"📨 Received from Deepgram: {message_type}")
        
        if message_type == "Welcome":
            await self.safe_send_json({
                "type": "welcome",
                "message": "Connected to Deepgram Voice Agent",
                "request_id": data.get("request_id")
            })
            
        elif message_type == "SettingsApplied":
            logger.info("✅ Deepgram Voice Agent settings applied")
            await self.safe_send_json({
                "type": "settings_applied",
                "message": "Voice Agent configured successfully"
            })
            # This is the signal for frontend to start sending audio
            await self.safe_send_json({
                "type": "ready_for_audio",
                "message": "Ready to receive audio"
            })
            
        elif message_type == "ConversationStarted":
            logger.info("🗣️ Conversation started")
            await self.safe_send_json({
                "type": "conversation_started",
                "message": "Conversation is ready"
            })
            
        elif message_type == "ConversationText":
            # Forward conversation text to frontend
            await self.safe_send_json({
                "type": "conversation_text",
                "text": data.get("content", ""),
                "role": data.get("role", "unknown")
            })
            
        elif message_type == "UserStartedSpeaking":
            await self.safe_send_json({
                "type": "user_started_speaking",
                "message": "User started speaking"
            })
            
        elif message_type == "AgentThinking":
            await self.safe_send_json({
                "type": "agent_thinking",
                "message": "Agent is thinking..."
            })
            
        elif message_type == "Error":
            error_msg = data.get("description", "Unknown error")
            logger.error(f"❌ Deepgram Voice Agent error: {error_msg}")
            await self.safe_send_json({
                "type": "error",
                "message": f"Voice Agent error: {error_msg}"
            })
            
        elif message_type == "Warning":
            warning_msg = data.get("description", "Unknown warning")
            logger.warning(f"⚠️ Deepgram Voice Agent warning: {warning_msg}")
            await self.safe_send_json({
                "type": "warning",
                "message": f"Voice Agent warning: {warning_msg}"
            })

    async def handle_deepgram_audio(self, audio_data: bytes):
        """Handle audio data from Deepgram Voice Agent"""
        try:
            # Convert binary audio to base64 for frontend
            b64_audio = base64.b64encode(audio_data).decode()
            
            await self.safe_send_json({
                "type": "audio",
                "audio": b64_audio,
                "format": "wav",
                "isFinal": False
            })
            
        except Exception as e:
            logger.error(f"❌ Error handling Deepgram audio: {e}")

    async def process_audio_stream(self, audio_data: bytes):
        """Forward audio to Deepgram Voice Agent"""
        try:
            if self.deepgram_ws and not self.deepgram_ws.closed:
                await self.deepgram_ws.send(audio_data)
                logger.debug(f"📤 Forwarded audio to Deepgram: {len(audio_data)} bytes")
            else:
                logger.warning(f"❌ Deepgram Voice Agent connection not available - ws: {self.deepgram_ws}, closed: {self.deepgram_ws.closed if self.deepgram_ws else 'N/A'}")
        except Exception as e:
            logger.error(f"❌ Error forwarding audio to Deepgram: {e}")
            # Check if connection is still alive
            if self.deepgram_ws:
                logger.error(f"WebSocket state: closed={self.deepgram_ws.closed}")
            else:
                logger.error("WebSocket is None")

    async def safe_send_json(self, data):
        """Safely send JSON to WebSocket with error handling"""
        if not self.is_connected:
            logger.debug("WebSocket disconnected, skipping message")
            return False
            
        try:
            await self.websocket.send_json(data)
            return True
        except Exception as e:
            if "Cannot call \"send\"" in str(e):
                self.is_connected = False
                logger.debug("WebSocket connection closed by client")
            else:
                logger.error(f"❌ Failed to send WebSocket message: {e}")
            return False

    async def get_bot_data(self):
        """Fetch bot configuration from database"""
        try:
            kb_manager = KBManager()
            bot_details = await asyncio.to_thread(kb_manager.get_kb_details, self.bot_id)
            
            if bot_details:
                return {
                    "kb_id": self.bot_id,
                    "name": bot_details.get("name", "AI Assistant"),
                    "company": bot_details.get("company_name", "Your Company"),
                    "custom_prompt": bot_details.get("custom_prompt")
                }
            else:
                # Fallback for demo bots
                return {
                    "kb_id": self.bot_id,
                    "name": "AI Assistant", 
                    "company": "Your Company",
                    "custom_prompt": None
                }
                
        except Exception as e:
            logger.error(f"❌ Error fetching bot data: {e}")
            return {
                "kb_id": self.bot_id,
                "name": "AI Assistant",
                "company": "Your Company", 
                "custom_prompt": None
            }

    async def cleanup(self):
        """Clean up connections"""
        try:
            self.is_connected = False
            
            if self.deepgram_ws and not self.deepgram_ws.closed:
                await self.deepgram_ws.close()
                
            # Log performance metrics
            if self.metrics["total_latency"]:
                avg_latency = sum(self.metrics["total_latency"]) / len(self.metrics["total_latency"])
                logger.info(f"Session {self.session_id} - Avg latency: {avg_latency:.2f}s")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

# WebSocket endpoint
@router.websocket("/ws/voice-agent/{bot_id}")
async def voice_agent_websocket_endpoint(websocket: WebSocket, bot_id: str):
    """Deepgram Voice Agent WebSocket endpoint"""
    await websocket.accept()
    session = DeepgramVoiceAgentSession(bot_id, websocket)
    
    try:
        # Initialize Deepgram Voice Agent connection
        await session.initialize()
        logger.info(f"✅ Voice Agent session started for bot {bot_id}")
        
        # Send connected confirmation
        await session.safe_send_json({
            "type": "connected",
            "bot_id": bot_id,
            "session_id": session.session_id
        })
        
        # Main message loop
        while True:
            message = await websocket.receive()
            
            if message["type"] == "websocket.receive":
                if "bytes" in message:
                    # Binary audio data - forward directly to Deepgram
                    try:
                        audio_data = message["bytes"]
                        logger.debug(f"📨 Received binary audio: {len(audio_data)} bytes")
                        await session.process_audio_stream(audio_data)
                    except Exception as e:
                        logger.error(f"❌ Audio processing error: {e}")
                elif "text" in message:
                    # JSON message
                    try:
                        data = json.loads(message["text"])
                        if data["type"] == "audio":
                            # Decode base64 audio and forward to Deepgram Voice Agent
                            audio_bytes = base64.b64decode(data["audio"])
                            await session.process_audio_stream(audio_bytes)
                        elif data["type"] == "control":
                            # Handle control messages (pause, resume, etc.)
                            if data.get("action") == "pause":
                                logger.info("🔇 Voice Agent paused")
                    except Exception as e:
                        logger.error(f"❌ Message processing error: {e}")
                    
    except WebSocketDisconnect:
        logger.info(f"Voice Agent session disconnected for bot {bot_id}")
    except Exception as e:
        logger.error(f"Voice Agent session error: {e}")
    finally:
        await session.cleanup()
        logger.info(f"Session {session.session_id} cleaned up")

# Health check endpoint
@router.get("/voice-agent/health")
async def voice_agent_health_check():
    """Check if Voice Agent services are available"""
    deepgram_available = bool(os.getenv("DEEPGRAM_API_KEY"))
    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    
    return {
        "status": "healthy",
        "services": {
            "deepgram_voice_agent": deepgram_available,
            "openai": openai_available
        }
    }