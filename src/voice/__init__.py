"""Voice infrastructure for PR Buddy.

Provides STT (speech-to-text) and TTS (text-to-speech) providers
for voice-enabled interactions.
"""

from .config import (
    PollyVoiceConfig,
    ElevenLabsVoiceConfig,
    WhisperSTTConfig,
    TTSVoiceConfig,
    STTVoiceConfig,
)
from .factory import create_tts, create_stt

__all__ = [
    # Config
    "PollyVoiceConfig",
    "ElevenLabsVoiceConfig",
    "WhisperSTTConfig",
    "TTSVoiceConfig",
    "STTVoiceConfig",
    # Factory
    "create_tts",
    "create_stt",
]

