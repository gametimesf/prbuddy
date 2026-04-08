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
class OpenAITTSConfig:
    """OpenAI TTS configuration."""

    voice_id: str = "alloy"  # alloy, echo, fable, onyx, nova, shimmer
    model: str = "tts-1-hd"  # tts-1 (fast, lower quality) or tts-1-hd (slower, natural)
    sample_rate: int = 24000  # OpenAI TTS outputs at 24kHz
    speed: float = 1.0  # 0.25 to 4.0 (1.0 = normal speed)


@dataclass
class WhisperSTTConfig:
    """OpenAI Whisper STT configuration."""
    
    model: str = "whisper-1"
    language: str | None = None  # None = auto-detect


# Type aliases for extensibility
TTSVoiceConfig = Union[PollyVoiceConfig, OpenAITTSConfig]
STTVoiceConfig = WhisperSTTConfig

