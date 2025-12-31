"""Base protocol for speech-to-text providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class STTProvider(ABC):
    """Abstract base class for speech-to-text providers.
    
    Implementations should handle audio input and produce text output.
    """
    
    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Get the expected audio sample rate."""
        ...
    
    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """Get list of supported audio formats."""
        ...
    
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Transcribe audio bytes to text.
        
        Args:
            audio: Audio bytes in the expected format.
        
        Returns:
            Transcribed text.
        """
        ...
    
    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[str]:
        """Stream audio and transcribe.
        
        Args:
            audio_stream: Async iterator of audio chunks.
        
        Yields:
            Transcribed text chunks.
        """
        ...

