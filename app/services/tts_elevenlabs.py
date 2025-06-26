from elevenlabs.client import ElevenLabs
import base64
import asyncio
import logging

class ElevenLabsTTS:
    def __init__(self, api_key: str, voice_id: str, model: str = "eleven_multilingual_v2"):
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id
        self.model = model
        self.logger = logging.getLogger(__name__)
    
    async def speak(self, text: str, send_chunk_callback):
        """Convert text to speech and stream audio chunks"""
        try:
            self.logger.info(f"🔊 Starting TTS for: '{text[:50]}...'")
            
            # Generate streaming audio
            audio_stream = self.client.text_to_speech.stream(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model,
                output_format="mp3_44100_128"
            )
            
            # Process each audio chunk
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    # Convert to base64 and send
                    b64_chunk = base64.b64encode(chunk).decode()
                    await send_chunk_callback(b64_chunk)
            
            self.logger.info("✅ TTS streaming completed")
            
        except Exception as e:
            self.logger.error(f"❌ ElevenLabs TTS error: {e}")
            raise 