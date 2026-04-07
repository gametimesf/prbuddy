"""Audio utilities for format conversion and processing."""

from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path


def decode_webm_to_pcm(webm_bytes: bytes, target_sample_rate: int = 24000) -> bytes:
    """Decode WebM audio to PCM16 bytes.
    
    Uses ffmpeg for conversion. Falls back to raw data if ffmpeg unavailable.
    
    Args:
        webm_bytes: WebM encoded audio bytes.
        target_sample_rate: Target sample rate for output PCM.
    
    Returns:
        PCM16 audio bytes at the target sample rate.
    """
    if not webm_bytes:
        return b""
    
    try:
        # Write input to temp file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(webm_bytes)
            input_path = f.name
        
        try:
            # Run ffmpeg to convert to PCM
            result = subprocess.run(
                [
                    "ffmpeg", "-i", input_path,
                    "-f", "s16le",  # PCM 16-bit little-endian
                    "-acodec", "pcm_s16le",
                    "-ac", "1",  # Mono
                    "-ar", str(target_sample_rate),  # Sample rate
                    "-loglevel", "error",
                    "pipe:1"  # Output to stdout
                ],
                capture_output=True,
                check=True,
            )
            return result.stdout
        finally:
            # Clean up temp file
            Path(input_path).unlink(missing_ok=True)
            
    except FileNotFoundError:
        # ffmpeg not installed - log warning and return empty
        import logging
        logging.warning("ffmpeg not found - cannot decode webm audio")
        return b""
    except subprocess.CalledProcessError as e:
        import logging
        logging.warning(f"ffmpeg error decoding audio: {e.stderr.decode()}")
        return b""


def detect_audio_format(data: bytes) -> str:
    """Detect audio format from magic bytes.
    
    Args:
        data: Audio data bytes.
    
    Returns:
        Format string: 'webm', 'wav', 'pcm', or 'unknown'.
    """
    if not data:
        return "unknown"
    
    # WebM starts with 0x1A45DFA3 (EBML header)
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return "webm"
    
    # WAV starts with 'RIFF'
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return "wav"
    
    # Assume PCM if no header detected
    return "pcm"


async def convert_to_pcm_async(
    audio_bytes: bytes,
    source_format: str | None = None,
    target_sample_rate: int = 24000,
) -> bytes:
    """Convert audio to PCM16 format asynchronously.
    
    Args:
        audio_bytes: Input audio bytes.
        source_format: Source format ('webm', 'wav', 'pcm') or None to auto-detect.
        target_sample_rate: Target sample rate.
    
    Returns:
        PCM16 audio bytes.
    """
    import asyncio
    
    if source_format is None:
        source_format = detect_audio_format(audio_bytes)
    
    if source_format == "pcm":
        return audio_bytes
    elif source_format == "webm":
        # Run ffmpeg conversion in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, decode_webm_to_pcm, audio_bytes, target_sample_rate
        )
    elif source_format == "wav":
        # Extract PCM from WAV
        import wave
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wav:
            return wav.readframes(wav.getnframes())
    else:
        # Unknown format - return as-is
        return audio_bytes


