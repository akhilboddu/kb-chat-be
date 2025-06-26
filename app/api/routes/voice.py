from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict, Optional, AsyncGenerator
import asyncio
import json
import base64
import time
import os
from dotenv import load_dotenv
import logging
from app.core import agent_manager
from app.core.supabase_kb_manager import KBManager
from app.core.prompts import DEFAULT_SYSTEM_PROMPT
from app.utils.cache_utils import get_cached_response, set_cached_response
import random

# Import SDK-based services
from app.services.stt_deepgram import DeepgramStreamer
from app.services.tts_elevenlabs import ElevenLabsTTS

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

class VoiceAssistantSession:
    """Manages a single voice assistant session using official SDKs"""
    
    def __init__(self, bot_id: str, websocket: WebSocket):
        self.bot_id = bot_id
        self.websocket = websocket
        self.conversation_id = f"voice_{bot_id}_{int(time.time())}"
        
        # API Configuration
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        self.tts_model = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
        
        # SDK service instances
        self.stt = None  # DeepgramStreamer
        self.tts = None  # ElevenLabsTTS
        
        # State management
        self.is_speaking = False
        self.is_processing = False
        self.conversation_history = []
        self.transcript_buffer = ""
        self.is_connected = True  # Track connection state
        self.tts_task = None  # Track TTS task for cancellation
        
        # Performance tracking
        self.metrics = {
            "stt_latency": [],
            "llm_latency": [],
            "tts_latency": [],
            "total_latency": []
        }
        
        # Timeout management
        self.speaking_timeout_task = None
        
    async def initialize(self):
        """Initialize voice services with SDKs"""
        try:
            logger.info(f"🎙️ Initializing voice session for bot {self.bot_id}")
            
            # Validate API keys
            if not self.elevenlabs_key:
                raise ValueError("❌ ElevenLabs API key is missing")
            if not self.deepgram_key:
                raise ValueError("❌ Deepgram API key is missing")
            
            # Get current event loop to pass to Deepgram
            loop = asyncio.get_event_loop()
            self.stt = DeepgramStreamer(self.deepgram_key, self._on_transcript, loop)
            deepgram_success = await self.stt.connect()
            
            # Initialize ElevenLabs TTS
            try:
                self.tts = ElevenLabsTTS(self.elevenlabs_key, self.voice_id, self.tts_model)
                elevenlabs_success = True
                logger.info("✅ ElevenLabs TTS initialized successfully")
            except Exception as e:
                logger.error(f"❌ ElevenLabs initialization failed: {e}")
                elevenlabs_success = False
            
            # Log connection status
            logger.info(f"🔗 Connection status - ElevenLabs: {elevenlabs_success}, Deepgram: {deepgram_success}")
            
            # Send service status to frontend
            await self.safe_send_json({
                "type": "service_status",
                "elevenlabs": elevenlabs_success,
                "deepgram": deepgram_success
            })
            
            # Send capabilities to frontend
            await self.safe_send_json({
                "type": "initialized",
                "capabilities": {
                    "speech_recognition": deepgram_success,
                    "text_to_speech": elevenlabs_success
                }
            })
            
            if elevenlabs_success:
                await self.send_greeting()
            
            logger.info("🎉 Voice assistant initialization completed")
            
        except Exception as e:
            logger.error(f"❌ Voice initialization failed: {e}")
            await self.safe_send_json({
                "type": "error",
                "message": f"Voice initialization failed: {str(e)}"
            })
            raise

    async def _on_transcript(self, data):
        """Handle transcript from Deepgram SDK"""
        try:
            transcript = data['channel']['alternatives'][0]['transcript']
            is_final = data.get('is_final', True)
            
            if transcript:
                logger.info(f"📝 Transcript: '{transcript}', final: {is_final}")
                
                await self.safe_send_json({
                    "type": "transcript",
                    "text": transcript,
                    "is_final": is_final
                })
                
                if is_final:
                    logger.info(f"✅ Processing final transcript: '{transcript}'")
                    # Send "thinking" signal to frontend
                    await self.safe_send_json({
                        "type": "ai_thinking",
                        "message": "Processing your message..."
                    })
                    # Process complete utterance
                    start_time = time.time()
                    await self.process_user_speech(transcript)
                    self.metrics["total_latency"].append(time.time() - start_time)
                    
        except Exception as e:
            logger.error(f"❌ Error processing transcript: {e}")

    async def process_audio_stream(self, audio_data: bytes):
        """Forward audio to Deepgram SDK"""
        if self.stt and not self.is_speaking:
            try:
                logger.debug(f"📤 Forwarding audio to Deepgram: {len(audio_data)} bytes")
                self.stt.send_audio(audio_data)
            except Exception as e:
                logger.error(f"❌ Error forwarding audio to Deepgram: {e}")
        else:
            if not self.stt:
                logger.warning("❌ Deepgram STT not initialized")
            if self.is_speaking:
                logger.debug("🔇 Not forwarding audio - AI is speaking")

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

    async def process_user_speech(self, text: str):
        """Process user speech through RAG pipeline"""
        if self.is_processing:
            return
            
        self.is_processing = True
        try:
            # -------------------------------------------
            # QUICK FILLER RESPONSE TO REDUCE PERCEIVED LATENCY
            # -------------------------------------------
            # Send a short filler phrase so the user hears an immediate reply
            filler_phrases = [
                "Let me see...",
                "Hmm...",
                "Okay...",
                "Sure...",
                "Right...",
            ]

            filler_task = None
            if self.tts and self.is_connected:
                try:
                    filler_phrase = random.choice(filler_phrases)
                    # Fire and forget – we'll await later to avoid overlap
                    filler_task = asyncio.create_task(self.stream_tts_filler(filler_phrase))
                except Exception as e:
                    logger.warning(f"Filler TTS failed: {e}")

            # Check cache first for common queries
            cached_response = None
            if len(text.strip()) > 10:
                cached_response = get_cached_response(self.bot_id, text)
            
            if cached_response:
                ai_response = cached_response["response"]
                logger.info(f"Using cached response for: {text[:50]}...")
            else:
                # Get bot data and customer context
                bot_data = await self.get_bot_data()
                customer_context = {
                    "customer_name": "Voice Customer",
                    "customer_email": "",
                    "bot_name": bot_data.get("name", "Assistant"),
                    "company_name": bot_data.get("company", "Company")
                }
                
                # Create agent executor with custom prompt if available
                agent_executor = agent_manager.create_agent_executor(
                    kb_id=bot_data["kb_id"],
                    bot_id=self.bot_id,
                    memory=None,
                    customer_context=customer_context
                )
                
                # Format conversation history
                history_str = self.format_conversation_history()
                
                # Process through RAG
                llm_start = time.time()
                response = await asyncio.to_thread(
                    agent_executor.invoke,
                    {"input": text, "chat_history": history_str}
                )
                self.metrics["llm_latency"].append(time.time() - llm_start)
                
                ai_response = response.get("output", "I'm sorry, I didn't understand that.")
                
                # Cache successful responses
                if "(needs help)" not in ai_response:
                    set_cached_response(self.bot_id, text, ai_response)
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": ai_response})
            
            # Send text response to frontend
            await self.safe_send_json({
                "type": "ai_response",
                "text": ai_response
            })
            
            # Ensure filler speech has completed to avoid audio overlap
            if filler_task and not filler_task.done():
                try:
                    await filler_task
                except Exception:
                    pass  # Ignore filler errors

            # Stream to TTS using SDK
            await self.stream_tts_response(ai_response)
            
        except Exception as e:
            logger.error(f"Error processing speech: {e}")
            await self.send_error_response()
        finally:
            self.is_processing = False

    async def stream_tts_response(self, text: str):
        """Use ElevenLabs SDK for TTS streaming"""
        if not self.is_connected:
            logger.debug("WebSocket disconnected, skipping TTS")
            return
            
        if not self.tts:
            logger.warning("❌ ElevenLabs TTS not initialized")
            return
            
        try:
            logger.info(f"🔊 Starting TTS for: '{text[:50]}...'")
            self.is_speaking = True
            
            # Track TTS task so we can cancel it if needed
            self.tts_task = asyncio.create_task(
                self.tts.speak(text, self._send_audio_chunk)
            )
            await self.tts_task
            
            # Send final marker
            await self.safe_send_json({
                "type": "audio",
                "audio": "",
                "isFinal": True,
                "format": "mp3"
            })
            
            self.is_speaking = False
            logger.info("✅ TTS streaming completed")
            
        except Exception as e:
            logger.error(f"❌ TTS streaming failed: {e}")
            self.is_speaking = False
            
            # Check if it's a quota exceeded error
            error_str = str(e)
            if "quota_exceeded" in error_str:
                logger.warning("⚠️ ElevenLabs quota exceeded - sending text-only response")
                # Don't try to send another TTS error message, just notify the user
                await self.safe_send_json({
                    "type": "tts_unavailable",
                    "message": "Voice synthesis temporarily unavailable (quota exceeded). Text responses will continue."
                })
            else:
                # For other errors, send error response but without TTS to avoid loops
                await self.safe_send_json({
                    "type": "ai_response", 
                    "text": "Sorry, I encountered an error with voice synthesis. I'll continue with text responses."
                })

    async def stream_tts_filler(self, text: str):
        """Stream a short filler phrase using turbo mode for lower latency"""
        if not self.is_connected or not self.tts:
            return
            
        try:
            logger.info(f"🏃 Streaming filler TTS (turbo): '{text}'")
            self.is_speaking = True
            
            # Use turbo mode for filler phrases
            await self.tts.speak(text, self._send_audio_chunk, use_turbo=True)
            
            # Send final marker
            await self.safe_send_json({
                "type": "audio",
                "audio": "",
                "isFinal": True,
                "format": "mp3"
            })
            
            self.is_speaking = False
            logger.info("✅ Filler TTS completed")
            
        except Exception as e:
            logger.warning(f"Filler TTS failed (non-critical): {e}")
            self.is_speaking = False

    async def _send_audio_chunk(self, b64_chunk: str):
        """Callback for sending audio chunks from TTS"""
        if not self.is_connected:
            return  # Don't send if disconnected
            
        await self.safe_send_json({
            "type": "audio",
            "audio": b64_chunk,
            "isFinal": False,
            "format": "mp3"
        })

    async def send_greeting(self):
        """Send initial greeting"""
        try:
            bot_data = await self.get_bot_data()
            greeting = f"Helloooo!! How can I help you today?"
            
            logger.info("🗣️ Sending greeting...")
            
            await self.safe_send_json({
                "type": "ai_response",
                "text": greeting
            })
            
            await self.stream_tts_response(greeting)
            
        except Exception as e:
            logger.error(f"❌ Error sending greeting: {e}")

    async def send_error_response(self):
        """Send error response to user"""
        error_message = "Sorry, I encountered an error. Please try again."
        
        await self.safe_send_json({
            "type": "ai_response", 
            "text": error_message
        })
        
        # Don't try TTS for error messages to avoid cascading failures
        logger.info("Sent text-only error response (TTS disabled for errors)")

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

    def format_conversation_history(self) -> str:
        """Format conversation history for prompt"""
        history = []
        for msg in self.conversation_history[-10:]:  # Last 10 messages
            role = "Human" if msg["role"] == "user" else "AI"
            history.append(f"{role}: {msg['content']}")
        return "\n".join(history)

    async def cleanup(self):
        """Clean up SDK connections"""
        try:
            self.is_connected = False  # Mark as disconnected
            
            # Cancel ongoing TTS if any
            if self.tts_task and not self.tts_task.done():
                self.tts_task.cancel()
                try:
                    await self.tts_task
                except asyncio.CancelledError:
                    pass
                    
            if self.stt:
                self.stt.close()
            
            if self.speaking_timeout_task:
                self.speaking_timeout_task.cancel()
                
            # Log performance metrics
            if self.metrics["total_latency"]:
                avg_latency = sum(self.metrics["total_latency"]) / len(self.metrics["total_latency"])
                logger.info(f"Session {self.conversation_id} - Avg latency: {avg_latency:.2f}s")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

# WebSocket endpoint
@router.websocket("/ws/voice/{bot_id}")
async def voice_websocket_endpoint(websocket: WebSocket, bot_id: str):
    """Main voice WebSocket endpoint using SDKs"""
    await websocket.accept()
    session = VoiceAssistantSession(bot_id, websocket)
    
    try:
        # Initialize SDK connections
        await session.initialize()
        logger.info(f"✅ Voice session started for bot {bot_id}")
        
        # Send connected confirmation
        await session.safe_send_json({
            "type": "connected",
            "bot_id": bot_id,
            "session_id": session.conversation_id
        })
        
        # Main message loop
        while True:
            data = await websocket.receive_json()
            
            if data["type"] == "audio":
                # Decode base64 audio and forward to Deepgram SDK
                try:
                    audio_bytes = base64.b64decode(data["audio"])
                    await session.process_audio_stream(audio_bytes)
                except Exception as e:
                    logger.error(f"❌ Audio processing error: {e}")
                    
            elif data["type"] == "control":
                # Handle control messages (pause, resume, etc.)
                if data.get("action") == "pause":
                    session.is_speaking = False
                    
    except WebSocketDisconnect:
        logger.info(f"Voice session disconnected for bot {bot_id}")
    except Exception as e:
        logger.error(f"Voice session error: {e}")
    finally:
        await session.cleanup()

# Health check endpoint
@router.get("/voice/health")
async def voice_health_check():
    """Check if voice services are available"""
    elevenlabs_available = bool(os.getenv("ELEVENLABS_API_KEY"))
    deepgram_available = bool(os.getenv("DEEPGRAM_API_KEY"))
    
    return {
        "status": "healthy",
        "services": {
            "elevenlabs": elevenlabs_available,
            "deepgram": deepgram_available
        }
    } 