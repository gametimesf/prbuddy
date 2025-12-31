"""Speech-to-text providers."""

from .base import STTProvider
from .whisper import WhisperSTTProvider

__all__ = ["STTProvider", "WhisperSTTProvider"]

