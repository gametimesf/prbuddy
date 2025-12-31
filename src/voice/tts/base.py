"""Base protocol for text-to-speech providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal


@dataclass
class TTSConfig:
    """Configuration for TTS synthesis."""
    
    voice_id: str
    sample_rate: int = 16000  # 16kHz is universally supported
    output_format: Literal["pcm", "mp3", "ogg"] = "pcm"


class TTSProvider(ABC):
    """Abstract base class for text-to-speech providers.
    
    Implementations should handle text input and produce audio output.
    """
    
    @abstractmethod
    async def synthesize(self, text: str, config: TTSConfig) -> bytes:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize.
            config: TTS configuration.
        
        Returns:
            Audio bytes in the configured format.
        """
        ...
    
    @abstractmethod
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
        ...
    
    @property
    @abstractmethod
    def available_voices(self) -> dict[str, str]:
        """Get available voices.
        
        Returns:
            Dict mapping voice_id to description.
        """
        ...
    
    def validate_voice(self, voice_id: str) -> bool:
        """Check if a voice ID is valid.
        
        Args:
            voice_id: Voice ID to validate.
        
        Returns:
            True if valid, False otherwise.
        """
        return voice_id in self.available_voices

