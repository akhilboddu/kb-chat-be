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
import queue
from argparse import Namespace

# Official Deepgram SDK imports
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    AgentWebSocketEvents,
    AgentKeepAlive,
)
from deepgram.clients.agent.v1.websocket.options import SettingsOptions  # type: ignore

from app.core import agent_manager

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
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")  # Use Anthropic instead of SambaNova
        
        # State management
        self.is_connected = True
        self.deepgram_client = None
        self.deepgram_connection = None
        self.audio_buffer = bytearray()
        self.processing_complete = False
        
        # Thread-safe message queue for communication between SDK thread and WebSocket thread
        self.message_queue = queue.Queue()
        self.message_sender_task = None
        
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
            if not self.openai_key and not self.anthropic_key:
                logger.warning("⚠️ Neither OpenAI nor Anthropic API key found - will use default LLM")
            
            # The base URL for our custom RAG endpoint
            # This should be your deployed backend URL
            base_url = os.getenv("VITE_API_BASE_URL", "http://localhost:8000")
            rag_provider_url = f"{base_url}/api/custom-voice-agent/rag-think"
            logger.info(f"--- DEBUG: Using Custom RAG Provider URL: {rag_provider_url} ---")
            logger.info(f"--- DEBUG: Bot ID: {self.bot_id} ---")
            logger.info(f"🚀 Using Custom RAG Think Provider at: {rag_provider_url}")
            
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
            
            # Audio output configuration (Voice Agent WebSocket doesn't support containerized formats)
            options.audio.output.encoding = "linear16"
            options.audio.output.sample_rate = 24000
            options.audio.output.container = "none"
            
            # Agent configuration
            options.agent.language = "en"
            options.agent.listen.provider.type = "deepgram"
            options.agent.listen.provider.model = "nova-3"
            # Configure the agent
            # Check if we should use custom provider or fallback to a supported one
            use_custom_provider = os.getenv("USE_CUSTOM_PROVIDER", "true").lower() == "true"
            
            if use_custom_provider:
                # Deepgram does not recognize an arbitrary "custom" provider type.
                # Instead, use the supported "open_ai" provider type and point it
                # at our own endpoint which speaks the OpenAI Chat Completions dialect.

                options.agent.think.provider.type = "open_ai"
                # Any string is accepted for BYO LLMs ‑ keep a harmless default.
                options.agent.think.provider.model = "gpt-3.5-turbo"
                # Do NOT include api_key in provider as it is not part of the API spec
                # Instead, put any auth info in endpoint.headers if needed (not required for our RAG backend)

                # Configure endpoint as a plain dict – Deepgram SDK will serialize this correctly
                options.agent.think.endpoint = {
                    "url": rag_provider_url,
                    "headers": {"x-kb-id": self.bot_id}
                }
                
                logger.info("🔧 Using CUSTOM RAG think provider via open_ai endpoint")
            else:
                # Fallback – use OpenAI directly
                options.agent.think.provider.type = "open_ai"
                options.agent.think.provider.model = "gpt-3.5-turbo"
                options.agent.think.provider.api_key = self.openai_key
                logger.info("🔧 Using OpenAI think provider (fallback)")
            
            options.agent.speak.provider.type = "deepgram"
            options.agent.speak.provider.model = "aura-2-thalia-en"
            options.agent.greeting = f"Hello! I'm {bot_data.get('name', 'your AI assistant')}. How can I help you today?"
            
            # Log the complete configuration for debugging
            logger.info("--- DEBUG: Complete agent configuration ---")
            logger.info(f"Think provider type: {options.agent.think.provider.type}")
            if use_custom_provider:
                if options.agent.think.endpoint:
                    logger.info(f"Think provider endpoint URL: {options.agent.think.endpoint.get('url')}")
                    logger.info(f"Think provider endpoint headers: {options.agent.think.endpoint.get('headers')}")
            else:
                logger.info(f"Think provider model: {options.agent.think.provider.model}")
                logger.info(f"Think provider has API key: {bool(options.agent.think.provider.api_key)}")
            
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
            
            # Start message sender task for thread-safe communication
            self.message_sender_task = asyncio.create_task(self.message_sender_loop())
            
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
            session.queue_message({
                "type": "welcome",
                "message": "Connected to Deepgram Voice Agent",
            })
        
        def on_settings_applied(connection, settings_applied, **kwargs):
            logger.info("✅ Settings applied")
            session.queue_message({
                "type": "settings_applied",
                "message": "Voice Agent configured successfully"
            })
        
        def on_conversation_text(connection, conversation_text, **kwargs):
            logger.info(f"💬 Conversation text: {conversation_text}")
            session.queue_message({
                "type": "conversation_text",
                "text": conversation_text.content,
                "role": conversation_text.role
            })
        
        def on_user_started_speaking(connection, user_started_speaking, **kwargs):
            logger.info("🗣️ User started speaking")
            session.queue_message({
                "type": "user_started_speaking",
                "message": "User started speaking"
            })
        
        def on_agent_thinking(connection, agent_thinking, **kwargs):
            logger.info("🤔 Agent thinking")
            session.queue_message({
                "type": "agent_thinking",
                "message": "Agent is thinking..."
            })
        
        def on_agent_started_speaking(connection, agent_started_speaking, **kwargs):
            logger.info("🤖 Agent started speaking")
            # Reset audio buffer for new response
            session.audio_buffer = bytearray()
            session.queue_message({
                "type": "agent_started_speaking",
                "message": "Agent started speaking"
            })
        
        def on_audio_data(connection, data, **kwargs):
            logger.debug(f"🔊 Received audio data: {len(data)} bytes")
            # Accumulate audio data
            session.audio_buffer.extend(data)
            
            # Convert to base64 and send to frontend
            b64_audio = base64.b64encode(data).decode()
            session.queue_message({
                "type": "audio",
                "audio": b64_audio,
                "format": "wav",
                "isFinal": False
            })
        
        def on_agent_audio_done(connection, agent_audio_done, **kwargs):
            logger.info("✅ Agent audio done")
            # Send final audio marker
            session.queue_message({
                "type": "audio",
                "audio": "",
                "isFinal": True,
                "format": "wav"
            })
            session.processing_complete = True
        
        def on_error(connection, error, **kwargs):
            logger.error(f"❌ Deepgram error: {error}")
            session.queue_message({
                "type": "error",
                "message": f"Voice Agent error: {error}"
            })
        
        def on_close(connection, close, **kwargs):
            logger.info(f"🔌 Connection closed: {close}")
            session.queue_message({
                "type": "close",
                "message": "Voice Agent connection closed"
            })
        
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
                        try:
                            logger.debug("💓 Sending keep alive")
                            self.deepgram_connection.send(str(AgentKeepAlive()))
                        except Exception as send_error:
                            # Connection might be closed - check specific error types
                            error_str = str(send_error).lower()
                            if ("closed" in error_str or 
                                "connection" in error_str or 
                                "websocket" in error_str or
                                "not connected" in error_str):
                                logger.info("🔌 Deepgram connection closed, stopping keep-alive")
                                self.is_connected = False
                                break
                            else:
                                logger.warning(f"⚠️ Keep alive send error (non-fatal): {send_error}")
                                # Don't break on temporary network issues
                except Exception as e:
                    logger.error(f"❌ Keep alive error: {e}")
                    self.is_connected = False
                    break
        
        keep_alive_thread = threading.Thread(target=send_keep_alive, daemon=True)
        keep_alive_thread.start()
        logger.info("✅ Keep-alive thread started")

    async def process_audio_stream(self, audio_data: bytes):
        """Forward audio to Deepgram Voice Agent using SDK"""
        try:
            if self.deepgram_connection and self.is_connected:
                # Check if connection is still active before sending
                try:
                    self.deepgram_connection.send(audio_data)
                    logger.debug(f"📤 Forwarded audio to Deepgram: {len(audio_data)} bytes")
                except Exception as send_error:
                    # Connection might be closed, mark as disconnected
                    error_str = str(send_error).lower()
                    if ("closed" in error_str or 
                        "connection" in error_str or 
                        "websocket" in error_str or
                        "not connected" in error_str):
                        self.is_connected = False
                        logger.warning("🔌 Deepgram connection closed during audio send")
                    else:
                        logger.warning(f"⚠️ Audio send error (non-fatal): {send_error}")
                        # Don't mark as disconnected for temporary network issues
            else:
                logger.warning("❌ Deepgram Voice Agent connection not available")
        except Exception as e:
            logger.error(f"❌ Error forwarding audio to Deepgram: {e}")
            # Only mark as disconnected on persistent connection errors
            if "connection" in str(e).lower() or "websocket" in str(e).lower():
                self.is_connected = False

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
        """Get bot configuration - simplified for pure conversation without KB dependency"""
        try:
            # For real-time conversation, we don't need KB data
            # Use a simple default configuration
            return {
                "kb_id": self.bot_id,
                "name": "Voice Assistant",
                "company": "AI Chat",
                "custom_prompt": (
                    "You are a helpful AI voice assistant. "
                    "Keep your responses conversational, concise, and natural for voice interaction. "
                    "Speak clearly and avoid very long responses. "
                    "Be engaging and helpful in your conversation."
                )
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Using fallback bot configuration: {e}")
            return {
                "kb_id": self.bot_id,
                "name": "Voice Assistant",
                "company": "AI Chat", 
                "custom_prompt": (
                    "You are a helpful AI voice assistant. "
                    "Keep your responses conversational and concise."
                )
            }

    async def cleanup(self):
        """Clean up connections"""
        if not self.is_connected:
            return  # Already cleaned up
            
        try:
            self.is_connected = False
            
            # Stop the message sender task
            if self.message_sender_task and not self.message_sender_task.done():
                self.message_sender_task.cancel()
                try:
                    await self.message_sender_task
                except asyncio.CancelledError:
                    pass
            
            if self.deepgram_connection:
                try:
                    # Safely close the Deepgram connection
                    self.deepgram_connection.finish()
                    logger.info("✅ Deepgram connection closed")
                except Exception as dg_error:
                    logger.warning(f"⚠️ Error closing Deepgram connection: {dg_error}")
                finally:
                    self.deepgram_connection = None
                
            # Log performance metrics
            if self.metrics["total_latency"]:
                avg_latency = sum(self.metrics["total_latency"]) / len(self.metrics["total_latency"])
                logger.info(f"Session {self.session_id} - Avg latency: {avg_latency:.2f}s")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
        finally:
            # Ensure cleanup state is set regardless of errors
            self.is_connected = False
            self.deepgram_connection = None
            self.message_sender_task = None

    async def message_sender_loop(self):
        """Process messages from the SDK thread and send them via WebSocket"""
        while self.is_connected:
            try:
                # Check for messages from the SDK thread
                try:
                    message = self.message_queue.get_nowait()
                    await self.safe_send_json(message)
                except queue.Empty:
                    # No messages, sleep briefly
                    await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"❌ Message sender loop error: {e}")
                break
    
    def queue_message(self, message):
        """Thread-safe method to queue messages from SDK thread"""
        try:
            self.message_queue.put_nowait(message)
        except queue.Full:
            logger.warning("⚠️ Message queue full, dropping message")
        except Exception as e:
            logger.error(f"❌ Error queuing message: {e}")

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
        while session.is_connected:
            try:
                message = await websocket.receive()
                
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        # Binary audio data - forward directly to Deepgram SDK (PREFERRED)
                        try:
                            audio_data = message["bytes"]
                            logger.debug(f"📨 Received binary audio: {len(audio_data)} bytes")
                            await session.process_audio_stream(audio_data)
                        except Exception as e:
                            logger.error(f"❌ Binary audio processing error: {e}")
                            # Don't break the loop for audio processing errors
                    elif "text" in message:
                        # JSON message - handle control messages and legacy base64 audio
                        try:
                            data = json.loads(message["text"])
                            if data["type"] == "audio" and "audio" in data:
                                # Legacy base64 audio support for compatibility
                                audio_bytes = base64.b64decode(data["audio"])
                                logger.debug(f"📨 Received base64 audio: {len(audio_bytes)} bytes")
                                await session.process_audio_stream(audio_bytes)
                            elif data["type"] == "control":
                                # Handle control messages (pause, resume, etc.)
                                if data.get("action") == "pause":
                                    logger.info("🔇 Voice Agent paused")
                                elif data.get("action") == "resume":
                                    logger.info("🔊 Voice Agent resumed")
                                elif data.get("action") == "disconnect":
                                    logger.info("🔌 Client requested disconnect")
                                    break
                            else:
                                logger.debug(f"📨 Other message type: {data.get('type', 'unknown')}")
                        except json.JSONDecodeError as e:
                            logger.warning(f"⚠️ Invalid JSON message: {e}")
                        except Exception as e:
                            logger.error(f"❌ Message processing error: {e}")
                            # Don't break the loop for message processing errors
                elif message["type"] == "websocket.disconnect":
                    logger.info("🔌 WebSocket disconnect message received")
                    break
                    
            except WebSocketDisconnect:
                logger.info("🔌 Client disconnected normally")
                break
            except Exception as e:
                if "Cannot call \"receive\"" in str(e) or "disconnect" in str(e).lower():
                    logger.info("🔌 WebSocket connection closed")
                    break
                else:
                    logger.error(f"❌ Unexpected error in message loop: {e}")
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"🔌 Voice Agent SDK session disconnected for bot {bot_id}")
    except Exception as e:
        if "Cannot call \"receive\"" in str(e):
            logger.info(f"🔌 WebSocket receive called after disconnect for bot {bot_id}")
        elif "disconnect" in str(e).lower():
            logger.info(f"🔌 WebSocket disconnected during operation for bot {bot_id}")
        else:
            logger.error(f"❌ Voice Agent SDK session error for bot {bot_id}: {e}")
    finally:
        await session.cleanup()
        logger.info(f"✅ Session {session.session_id} cleaned up")

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