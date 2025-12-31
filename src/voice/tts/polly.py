"""Amazon Polly text-to-speech provider."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import TTSProvider, TTSConfig

try:
    import boto3
except ImportError:
    boto3 = None


class PollyTTSProvider(TTSProvider):
    """Amazon Polly TTS implementation.
    
    Uses AWS Polly's Neural engine for natural-sounding speech.
    
    Note: Neural engine supports sample rates: 16000, 22050, 24000
    Standard engine supports: 8000, 16000, 22050
    """
    
    # Valid sample rates for neural engine
    VALID_SAMPLE_RATES = {16000, 22050, 24000}
    
    # Neural voices available in Polly (US English and British English)
    VOICES = {
        # US English - Female
        "Joanna": "US English, Female (Neural)",
        "Kendra": "US English, Female (Neural)",
        "Kimberly": "US English, Female (Neural)",
        "Salli": "US English, Female (Neural)",
        "Ivy": "US English, Female child (Neural)",
        # US English - Male
        "Matthew": "US English, Male (Neural)",
        "Joey": "US English, Male (Neural)",
        "Justin": "US English, Male child (Neural)",
        "Kevin": "US English, Male child (Neural)",
        # British English - Female
        "Amy": "British English, Female (Neural)",
        "Emma": "British English, Female (Neural)",
        # British English - Male
        "Brian": "British English, Male (Neural)",
        "Arthur": "British English, Male (Neural)",
    }
    
    def __init__(self, region: str = "us-west-2") -> None:
        """Initialize Polly provider.
        
        Args:
            region: AWS region for Polly API.
        """
        if boto3 is None:
            raise ImportError(
                "boto3 is required for PollyTTSProvider. "
                "Install with: pip install boto3"
            )
        
        self._region = region
        self._client = boto3.client("polly", region_name=region)
    
    @property
    def available_voices(self) -> dict[str, str]:
        return self.VOICES.copy()
    
    def _get_valid_sample_rate(self, requested: int) -> str:
        """Get a valid sample rate for Polly neural engine."""
        if requested in self.VALID_SAMPLE_RATES:
            return str(requested)
        # Default to 16000 if invalid
        return "16000"
    
    async def synthesize(self, text: str, config: TTSConfig) -> bytes:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Returns:
            PCM16 audio bytes.
        """
        sample_rate = self._get_valid_sample_rate(config.sample_rate)
        
        # Run boto3 call in executor since it's synchronous
        loop = asyncio.get_event_loop()
        
        response = await loop.run_in_executor(
            None,
            lambda: self._client.synthesize_speech(
                Text=text,
                OutputFormat="pcm",
                VoiceId=config.voice_id,
                Engine="neural",
                SampleRate=sample_rate,
            ),
        )
        
        # Read the audio stream
        audio_stream = response["AudioStream"]
        audio_data = await loop.run_in_executor(None, audio_stream.read)
        
        return audio_data
    
    async def synthesize_stream(
        self,
        text: str,
        config: TTSConfig,
    ) -> AsyncIterator[bytes]:
        """Stream synthesized audio chunks.
        
        Polly returns the full audio, but we chunk it for streaming.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Yields:
            Audio byte chunks (4KB each).
        """
        sample_rate = self._get_valid_sample_rate(config.sample_rate)
        loop = asyncio.get_event_loop()
        
        response = await loop.run_in_executor(
            None,
            lambda: self._client.synthesize_speech(
                Text=text,
                OutputFormat="pcm",
                VoiceId=config.voice_id,
                Engine="neural",
                SampleRate=sample_rate,
            ),
        )
        
        # Stream the audio in chunks
        audio_stream = response["AudioStream"]
        chunk_size = 4096  # 4KB chunks
        
        while True:
            chunk = await loop.run_in_executor(
                None,
                lambda: audio_stream.read(chunk_size),
            )
            if not chunk:
                break
            yield chunk
    
    def get_voice_for_locale(self, locale: str = "en-US") -> str:
        """Get a default voice for a locale.
        
        Args:
            locale: Locale code (e.g., "en-US", "en-GB").
        
        Returns:
            Voice ID suitable for the locale.
        """
        locale_voices = {
            "en-US": "Joanna",
            "en-GB": "Amy",
        }
        return locale_voices.get(locale, "Joanna")

