"""ElevenLabs text-to-speech provider."""

from __future__ import annotations

import os
from typing import AsyncIterator

from .base import TTSProvider, TTSConfig

try:
    from elevenlabs import AsyncElevenLabs
except ImportError:
    AsyncElevenLabs = None


class ElevenLabsTTSProvider(TTSProvider):
    """ElevenLabs TTS implementation.
    
    Uses ElevenLabs API for high-quality AI voices.
    """
    
    # Default voices - actual list fetched from API
    DEFAULT_VOICES = {
        "Rachel": "American Female, Conversational",
        "Drew": "American Male, Well-rounded",
        "Clyde": "American Male, War veteran",
        "Paul": "American Male, Ground reporter",
        "Domi": "American Female, Strong",
        "Dave": "British Male, Conversational",
        "Fin": "Irish Male, Sailor",
        "Sarah": "American Female, Soft news",
        "Antoni": "American Male, Well-rounded",
        "Thomas": "American Male, Calm",
        "Charlie": "Australian Male, Casual",
        "George": "British Male, Raspy",
        "Emily": "American Female, Calm",
        "Elli": "American Female, Emotional",
        "Callum": "American Male, Hoarse",
        "Patrick": "American Male, Shouty",
        "Harry": "American Male, Anxious",
        "Liam": "American Male, Articulate",
        "Dorothy": "British Female, Pleasant",
        "Josh": "American Male, Deep",
        "Arnold": "American Male, Crisp",
        "Charlotte": "Swedish Female, Seductive",
        "Matilda": "American Female, Warm",
        "Matthew": "British Male, Audiobook",
        "James": "Australian Male, Calm",
        "Joseph": "British Male, Articulate",
        "Jeremy": "American Male, Excited",
        "Michael": "American Male, Orotund",
        "Ethan": "American Male, Narrator",
        "Gigi": "American Female, Childish",
        "Freya": "American Female, Overhyped",
        "Grace": "American Female, Orotund",
        "Daniel": "British Male, Deep",
        "Serena": "American Female, Pleasant",
        "Adam": "American Male, Deep",
        "Nicole": "American Female, Whisper",
        "Jessie": "American Male, Raspy",
        "Ryan": "American Male, Soldier",
        "Sam": "American Male, Raspy",
        "Glinda": "American Female, Witch",
        "Giovanni": "English-Italian Male, Foreigner",
        "Mimi": "English-Swedish Female, Childish",
    }
    
    def __init__(self, api_key: str | None = None) -> None:
        """Initialize ElevenLabs provider.
        
        Args:
            api_key: ElevenLabs API key. Uses ELEVENLABS_API_KEY env var if not provided.
        """
        if AsyncElevenLabs is None:
            raise ImportError(
                "elevenlabs is required for ElevenLabsTTSProvider. "
                "Install with: pip install elevenlabs"
            )
        
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self._api_key:
            raise ValueError(
                "ElevenLabs API key required. "
                "Set ELEVENLABS_API_KEY env var or pass api_key."
            )
        
        self._client = AsyncElevenLabs(api_key=self._api_key)
        self._voice_cache: dict[str, str] | None = None
    
    @property
    def available_voices(self) -> dict[str, str]:
        """Get available voices.
        
        Returns cached default voices. Call fetch_voices() for live list.
        """
        return self.DEFAULT_VOICES.copy()
    
    async def fetch_voices(self) -> dict[str, str]:
        """Fetch available voices from the API.
        
        Returns:
            Dict mapping voice name to description.
        """
        if self._voice_cache is not None:
            return self._voice_cache
        
        try:
            response = await self._client.voices.get_all()
            self._voice_cache = {
                voice.name: voice.description or voice.labels.get("description", "")
                for voice in response.voices
            }
            return self._voice_cache
        except Exception:
            return self.DEFAULT_VOICES.copy()
    
    async def _get_voice_id(self, voice_name: str) -> str:
        """Get the voice ID for a voice name.
        
        Args:
            voice_name: The voice name to look up.
        
        Returns:
            The voice ID.
        """
        try:
            response = await self._client.voices.get_all()
            for voice in response.voices:
                if voice.name == voice_name:
                    return voice.voice_id
        except Exception:
            pass
        
        # Return the name as-is if not found (might be an ID already)
        return voice_name
    
    async def synthesize(self, text: str, config: TTSConfig) -> bytes:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Returns:
            Audio bytes.
        """
        voice_id = await self._get_voice_id(config.voice_id)
        
        audio = await self._client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="pcm_16000",
        )
        
        # Collect all chunks
        chunks = []
        async for chunk in audio:
            chunks.append(chunk)
        
        return b"".join(chunks)
    
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
        voice_id = await self._get_voice_id(config.voice_id)
        
        audio = await self._client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="pcm_16000",
        )
        
        async for chunk in audio:
            yield chunk

