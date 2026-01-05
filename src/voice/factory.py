"""Factory functions for creating voice providers.

Creates provider instances from typed configuration classes,
centralizing provider instantiation and ensuring type safety.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import PollyVoiceConfig, OpenAITTSConfig, WhisperSTTConfig, TTSVoiceConfig, STTVoiceConfig

if TYPE_CHECKING:
    from .tts.base import TTSProvider, TTSConfig
    from .stt.base import STTProvider


def create_tts(config: TTSVoiceConfig) -> tuple["TTSProvider", "TTSConfig"]:
    """Create a TTS provider and config from a voice config.
    
    Args:
        config: Provider-specific voice configuration.
    
    Returns:
        Tuple of (TTSProvider instance, TTSConfig for synthesis).
    
    Raises:
        ValueError: If config type is not recognized.
    """
    if isinstance(config, OpenAITTSConfig):
        from .tts.openai_tts import OpenAITTSProvider
        from .tts.base import TTSConfig

        return (
            OpenAITTSProvider(model=config.model),
            TTSConfig(
                voice_id=config.voice_id,
                sample_rate=config.sample_rate,
                speed=config.speed,
            ),
        )
    
    if isinstance(config, PollyVoiceConfig):
        from .tts.polly import PollyTTSProvider
        from .tts.base import TTSConfig
        
        return (
            PollyTTSProvider(),
            TTSConfig(
                voice_id=config.voice_id,
                sample_rate=config.sample_rate,
            ),
        )
    
    # Default to OpenAI TTS if unknown config
    from .tts.openai_tts import OpenAITTSProvider
    from .tts.base import TTSConfig
    
    return (
        OpenAITTSProvider(),
        TTSConfig(
            voice_id="alloy",
            sample_rate=24000,
        ),
    )


def create_stt(config: STTVoiceConfig) -> "STTProvider":
    """Create an STT provider from a voice config.
    
    Args:
        config: Provider-specific STT configuration.
    
    Returns:
        STTProvider instance.
    
    Raises:
        ValueError: If config type is not recognized.
    """
    if isinstance(config, WhisperSTTConfig):
        from .stt.whisper import WhisperSTTProvider
        
        return WhisperSTTProvider()
    
    raise ValueError(f"Unknown STT config type: {type(config).__name__}")

