"""Provider-specific voice configuration classes.

Each provider has its own config dataclass with appropriate defaults.
This allows type-safe configuration without mixing provider-specific
fields in a generic config class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass
class PollyVoiceConfig:
    """Amazon Polly TTS configuration."""
    
    voice_id: str = "Joanna"
    engine: str = "neural"
    sample_rate: int = 16000  # 16kHz for neural voices


@dataclass
class ElevenLabsVoiceConfig:
    """ElevenLabs TTS configuration."""
    
    voice_id: str = "Rachel"  # Default voice name
    model_id: str = "eleven_multilingual_v2"  # Latest multilingual model
    sample_rate: int = 16000  # 16kHz for consistency with Polly


@dataclass
class WhisperSTTConfig:
    """OpenAI Whisper STT configuration."""
    
    model: str = "whisper-1"
    language: str | None = None  # None = auto-detect


# Type aliases for extensibility
TTSVoiceConfig = Union[PollyVoiceConfig, ElevenLabsVoiceConfig]
STTVoiceConfig = Union[WhisperSTTConfig]

