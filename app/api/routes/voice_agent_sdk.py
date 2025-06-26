from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, Optional
import asyncio
import json
import base64
import time
import os
from dotenv import load_dotenv
import logging
import threading

# Official Deepgram SDK imports
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    AgentWebSocketEvents,
    AgentKeepAlive,
)
from deepgram.clients.agent.v1.websocket.options import SettingsOptions

from app.core import agent_manager
from app.core.supabase_kb_manager import KBManager

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-agent-sdk"])

class DeepgramVoiceAgentSDK:
    """Voice Agent using official Deepgram SDK"""
    
    def __init__(self, bot_id: str, websocket: WebSocket):
        self.bot_id = bot_id
        self.websocket = websocket
        self.session_id = f"voice_agent_sdk_{bot_id}_{int(time.time())}"
        
        # API Configuration
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        
        # State management
        self.is_connected = True
        self.deepgram_client = None
        self.deepgram_connection = None
        self.audio_buffer = bytearray()
        self.processing_complete = False
        
        # Performance tracking
        self.metrics = {
            "total_latency": []
        }
        
    async def initialize(self):
        """Initialize Deepgram Voice Agent using official SDK"""
        try:
            logger.info(f"🎙️ Initializing Deepgram Voice Agent SDK for bot {self.bot_id}")
            
            # Validate API keys
            if not self.deepgram_key:
                raise ValueError("❌ Deepgram API key is missing")
            if not self.openai_key:
                logger.warning("⚠️ OpenAI API key is missing - will use default LLM")
            
            # Initialize Deepgram client with official SDK
            config = DeepgramClientOptions(
                options={
                    "keepalive": "true",
                }
            )
            self.deepgram_client = DeepgramClient(self.deepgram_key, config)
            self.deepgram_connection = self.deepgram_client.agent.websocket.v("1")
            
            logger.info("✅ Deepgram SDK client initialized")
            
            # Set up event handlers
            self.setup_event_handlers()
            
            # Get bot configuration for custom prompt
            bot_data = await self.get_bot_data()
            
            # Configure the Agent using official SDK
            options = SettingsOptions()
            
            # Audio input configuration (16kHz for input, 24kHz for output as per docs)
            options.audio.input.encoding = "linear16"
            options.audio.input.sample_rate = 16000
            
            # Audio output configuration
            options.audio.output.encoding = "linear16"
            options.audio.output.sample_rate = 24000
            options.audio.output.container = "wav"
            
            # Agent configuration
            options.agent.language = "en"
            options.agent.listen.provider.type = "deepgram"
            options.agent.listen.provider.model = "nova-3"
            options.agent.think.provider.type = "open_ai"
            options.agent.think.provider.model = "gpt-4o-mini"
            options.agent.think.prompt = bot_data.get("custom_prompt") or "You are a helpful AI assistant."
            options.agent.speak.provider.type = "deepgram"
            options.agent.speak.provider.model = "aura-2-thalia-en"
            options.agent.greeting = f"Hello! I'm {bot_data.get('name', 'your AI assistant')}. How can I help you today?"
            
            # Start the connection using official SDK
            logger.info("🔗 Starting Deepgram Voice Agent connection...")
            if not self.deepgram_connection.start(options):
                raise RuntimeError("Failed to start Deepgram Voice Agent connection")
            
            logger.info("✅ Deepgram Voice Agent SDK initialized successfully")
            
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
            
            # Start keep-alive in a separate thread
            self.start_keep_alive()
            
        except Exception as e:
            logger.error(f"❌ Voice Agent SDK initialization failed: {e}")
            await self.safe_send_json({
                "type": "error",
                "message": f"Voice Agent initialization failed: {str(e)}"
            })
            raise

    def setup_event_handlers(self):
        """Set up event handlers for Deepgram SDK"""
        
        # Store self reference for use in closures
        session = self
        
        def on_welcome(connection, welcome, **kwargs):
            logger.info(f"📨 Welcome: {welcome}")
            asyncio.create_task(session.safe_send_json({
                "type": "welcome",
                "message": "Connected to Deepgram Voice Agent",
            }))
        
        def on_settings_applied(connection, settings_applied, **kwargs):
            logger.info("✅ Settings applied")
            asyncio.create_task(session.safe_send_json({
                "type": "settings_applied",
                "message": "Voice Agent configured successfully"
            }))
        
        def on_conversation_text(connection, conversation_text, **kwargs):
            logger.info(f"💬 Conversation text: {conversation_text}")
            asyncio.create_task(session.safe_send_json({
                "type": "conversation_text",
                "text": conversation_text.content,
                "role": conversation_text.role
            }))
        
        def on_user_started_speaking(connection, user_started_speaking, **kwargs):
            logger.info("🗣️ User started speaking")
            asyncio.create_task(session.safe_send_json({
                "type": "user_started_speaking",
                "message": "User started speaking"
            }))
        
        def on_agent_thinking(connection, agent_thinking, **kwargs):
            logger.info("🤔 Agent thinking")
            asyncio.create_task(session.safe_send_json({
                "type": "agent_thinking",
                "message": "Agent is thinking..."
            }))
        
        def on_agent_started_speaking(connection, agent_started_speaking, **kwargs):
            logger.info("🤖 Agent started speaking")
            # Reset audio buffer for new response
            session.audio_buffer = bytearray()
            asyncio.create_task(session.safe_send_json({
                "type": "agent_started_speaking",
                "message": "Agent started speaking"
            }))
        
        def on_audio_data(connection, data, **kwargs):
            logger.debug(f"🔊 Received audio data: {len(data)} bytes")
            # Accumulate audio data
            session.audio_buffer.extend(data)
            
            # Convert to base64 and send to frontend
            b64_audio = base64.b64encode(data).decode()
            asyncio.create_task(session.safe_send_json({
                "type": "audio",
                "audio": b64_audio,
                "format": "wav",
                "isFinal": False
            }))
        
        def on_agent_audio_done(connection, agent_audio_done, **kwargs):
            logger.info("✅ Agent audio done")
            # Send final audio marker
            asyncio.create_task(session.safe_send_json({
                "type": "audio",
                "audio": "",
                "isFinal": True,
                "format": "wav"
            }))
            session.processing_complete = True
        
        def on_error(connection, error, **kwargs):
            logger.error(f"❌ Deepgram error: {error}")
            asyncio.create_task(session.safe_send_json({
                "type": "error",
                "message": f"Voice Agent error: {error}"
            }))
        
        def on_close(connection, close, **kwargs):
            logger.info(f"🔌 Connection closed: {close}")
            asyncio.create_task(session.safe_send_json({
                "type": "close",
                "message": "Voice Agent connection closed"
            }))
        
        def on_unhandled(connection, unhandled, **kwargs):
            logger.warning(f"❓ Unhandled event: {unhandled}")
        
        # Register all event handlers
        self.deepgram_connection.on(AgentWebSocketEvents.Welcome, on_welcome)
        self.deepgram_connection.on(AgentWebSocketEvents.SettingsApplied, on_settings_applied)
        self.deepgram_connection.on(AgentWebSocketEvents.ConversationText, on_conversation_text)
        self.deepgram_connection.on(AgentWebSocketEvents.UserStartedSpeaking, on_user_started_speaking)
        self.deepgram_connection.on(AgentWebSocketEvents.AgentThinking, on_agent_thinking)
        self.deepgram_connection.on(AgentWebSocketEvents.AgentStartedSpeaking, on_agent_started_speaking)
        self.deepgram_connection.on(AgentWebSocketEvents.AudioData, on_audio_data)
        self.deepgram_connection.on(AgentWebSocketEvents.AgentAudioDone, on_agent_audio_done)
        self.deepgram_connection.on(AgentWebSocketEvents.Error, on_error)
        self.deepgram_connection.on(AgentWebSocketEvents.Close, on_close)
        self.deepgram_connection.on(AgentWebSocketEvents.Unhandled, on_unhandled)
        
        logger.info("✅ Event handlers registered")

    def start_keep_alive(self):
        """Start keep-alive messages in a separate thread"""
        def send_keep_alive():
            while self.is_connected:
                try:
                    time.sleep(5)
                    if self.deepgram_connection and self.is_connected:
                        logger.debug("💓 Sending keep alive")
                        self.deepgram_connection.send(str(AgentKeepAlive()))
                except Exception as e:
                    logger.error(f"❌ Keep alive error: {e}")
                    break
        
        keep_alive_thread = threading.Thread(target=send_keep_alive, daemon=True)
        keep_alive_thread.start()
        logger.info("✅ Keep-alive thread started")

    async def process_audio_stream(self, audio_data: bytes):
        """Forward audio to Deepgram Voice Agent using SDK"""
        try:
            if self.deepgram_connection and self.is_connected:
                self.deepgram_connection.send(audio_data)
                logger.debug(f"📤 Forwarded audio to Deepgram: {len(audio_data)} bytes")
            else:
                logger.warning("❌ Deepgram Voice Agent connection not available")
        except Exception as e:
            logger.error(f"❌ Error forwarding audio to Deepgram: {e}")

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
            
            if self.deepgram_connection:
                self.deepgram_connection.finish()
                
            # Log performance metrics
            if self.metrics["total_latency"]:
                avg_latency = sum(self.metrics["total_latency"]) / len(self.metrics["total_latency"])
                logger.info(f"Session {self.session_id} - Avg latency: {avg_latency:.2f}s")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

# WebSocket endpoint using official SDK
@router.websocket("/ws/voice-agent-sdk/{bot_id}")
async def voice_agent_sdk_websocket_endpoint(websocket: WebSocket, bot_id: str):
    """Voice Agent WebSocket endpoint using official Deepgram SDK"""
    await websocket.accept()
    session = DeepgramVoiceAgentSDK(bot_id, websocket)
    
    try:
        # Initialize SDK connection
        await session.initialize()
        logger.info(f"✅ Voice Agent SDK session started for bot {bot_id}")
        
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
                    # Binary audio data - forward directly to Deepgram SDK
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
                            # Decode base64 audio and forward to Deepgram SDK
                            audio_bytes = base64.b64decode(data["audio"])
                            await session.process_audio_stream(audio_bytes)
                        elif data["type"] == "control":
                            # Handle control messages (pause, resume, etc.)
                            if data.get("action") == "pause":
                                logger.info("🔇 Voice Agent paused")
                    except Exception as e:
                        logger.error(f"❌ Message processing error: {e}")
                    
    except WebSocketDisconnect:
        logger.info(f"Voice Agent SDK session disconnected for bot {bot_id}")
    except Exception as e:
        logger.error(f"Voice Agent SDK session error: {e}")
    finally:
        await session.cleanup()
        logger.info(f"Session {session.session_id} cleaned up")

# Health check endpoint
@router.get("/voice-agent-sdk/health")
async def voice_agent_sdk_health_check():
    """Check if Voice Agent SDK services are available"""
    deepgram_available = bool(os.getenv("DEEPGRAM_API_KEY"))
    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    
    return {
        "status": "healthy",
        "services": {
            "deepgram_voice_agent_sdk": deepgram_available,
            "openai": openai_available
        }
    } 