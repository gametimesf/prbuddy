"""OpenAI text-to-speech provider."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import TTSProvider, TTSConfig


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS implementation.
    
    Uses OpenAI's TTS API for natural-sounding speech.
    Supports 'tts-1' and 'tts-1-hd' models.
    """
    
    # Available voices in OpenAI TTS
    VOICES = {
        "alloy": "Neutral, balanced voice",
        "echo": "Warm male voice",
        "fable": "British accent",
        "onyx": "Deep male voice",
        "nova": "Female voice, youthful",
        "shimmer": "Female voice, warm",
    }
    
    def __init__(self, model: str = "tts-1") -> None:
        """Initialize OpenAI TTS provider.
        
        Args:
            model: TTS model to use ('tts-1' or 'tts-1-hd').
        """
        self._client = AsyncOpenAI()
        self._model = model
    
    @property
    def available_voices(self) -> dict[str, str]:
        return self.VOICES.copy()
    
    @property
    def sample_rate(self) -> int:
        """OpenAI TTS outputs at 24kHz."""
        return 24000
    
    async def synthesize(self, text: str, config: TTSConfig) -> bytes:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Returns:
            PCM16 audio bytes.
        """
        # OpenAI TTS uses 'voice' from config.voice_id
        voice = config.voice_id if config.voice_id in self.VOICES else "alloy"
        
        response = await self._client.audio.speech.create(
            model=self._model,
            voice=voice,
            input=text,
            response_format="pcm",  # Raw PCM audio
            speed=config.speed,  # 0.25 to 4.0
        )
        
        # Read all bytes from the response
        return response.content
    
    async def synthesize_stream(
        self,
        text: str,
        config: TTSConfig,
    ) -> AsyncIterator[bytes]:
        """Stream synthesized audio chunks.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Yields:
            Audio byte chunks.
        """
        voice = config.voice_id if config.voice_id in self.VOICES else "alloy"
        
        # Use streaming response
        async with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=voice,
            input=text,
            response_format="pcm",
            speed=config.speed,  # 0.25 to 4.0
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk
    
    def get_voice_for_locale(self, locale: str = "en-US") -> str:
        """Get a default voice for a locale.
        
        Args:
            locale: Locale code (ignored, returns default).
        
        Returns:
            Default voice ID.
        """
        return "alloy"


