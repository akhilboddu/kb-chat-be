from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
import asyncio
import logging
import json

class DeepgramStreamer:
    def __init__(self, api_key: str, on_transcript_callback, loop=None):
        self.client = DeepgramClient(api_key)
        self.connection = None
        self.on_transcript_callback = on_transcript_callback
        self.logger = logging.getLogger(__name__)
        self.loop = loop or asyncio.get_event_loop()
    
    async def connect(self):
        """Initialize WebSocket connection to Deepgram using official SDK"""
        try:
            self.logger.info("🔗 Connecting to Deepgram with official SDK...")
            
            # Create WebSocket connection using official SDK method
            self.connection = self.client.listen.websocket.v("1")
            
            # Set up event handlers using exact SDK pattern from docs
            self.connection.on(LiveTranscriptionEvents.Open, self._on_open)
            self.connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
            self.connection.on(LiveTranscriptionEvents.Error, self._on_error)
            self.connection.on(LiveTranscriptionEvents.Close, self._on_close)
            
            # Configure live options exactly as in documentation
            options = LiveOptions(
                model="nova-2",
                punctuate=True,
                language="en-US",
                encoding="linear16",  # Changed back to linear16
                channels=1,
                sample_rate=16000,   # Changed back to 16000 for linear16
                interim_results=True,
                utterance_end_ms="1000",
                vad_events=True,
            )
            
            # Start the connection
            if self.connection.start(options):
                self.logger.info("✅ Deepgram WebSocket connected successfully")
                return True
            else:
                self.logger.error("❌ Failed to start Deepgram connection")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Deepgram connection failed: {e}")
            return False
    
    def _on_open(self, connection, open, **kwargs):
        """Handle WebSocket open event"""
        self.logger.info("🔌 Deepgram WebSocket connection opened")
    
    def _on_transcript(self, connection, result, **kwargs):
        """Handle transcript messages with exact SDK signature"""
        try:
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            
            self.logger.debug(f"📝 Transcript: '{sentence}', final: {result.is_final}")
            
            # Call the callback with transcript data using thread-safe method
            transcript_data = {
                'channel': {
                    'alternatives': [{'transcript': sentence}]
                },
                'is_final': result.is_final if hasattr(result, 'is_final') else True
            }
            
            # Get the current event loop from the main thread
            try:
                # Use the stored event loop
                # Schedule the async callback to run in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.on_transcript_callback(transcript_data),
                    self.loop
                )
            except RuntimeError:
                # No running event loop, try to call it synchronously
                # This is a fallback, but the callback is async so we need to handle it properly
                self.logger.error("No running event loop found for transcript callback")
                         
        except Exception as e:
            self.logger.error(f"❌ Error processing transcript: {e}")
    
    def _on_error(self, connection, error, **kwargs):
        """Handle WebSocket errors"""
        self.logger.error(f"❌ Deepgram WebSocket error: {error}")
    
    def _on_close(self, connection, close, **kwargs):
        """Handle WebSocket close event"""
        self.logger.info("�� Deepgram WebSocket connection closed")
    
    def send_audio(self, audio_data: bytes):
        """Send audio data to Deepgram"""
        try:
            if self.connection:
                self.connection.send(audio_data)
            else:
                self.logger.warning("❌ Deepgram connection not established")
        except Exception as e:
            self.logger.error(f"❌ Error sending audio to Deepgram: {e}")
    
    def close(self):
        """Close the Deepgram connection"""
        try:
            if self.connection:
                self.connection.finish()
                self.logger.info("✅ Deepgram connection closed")
        except Exception as e:
            self.logger.error(f"❌ Error closing Deepgram connection: {e}") 