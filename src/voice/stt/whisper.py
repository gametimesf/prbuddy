"""OpenAI Whisper speech-to-text provider."""

from __future__ import annotations

import io
import wave
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import STTProvider


class WhisperSTTProvider(STTProvider):
    """OpenAI Whisper STT implementation.
    
    Uses OpenAI's Whisper API for transcription.
    Accepts PCM16 audio at 24kHz (matches OpenAI Realtime API format).
    """
    
    def __init__(
        self,
        *,
        model: str = "whisper-1",
        language: str | None = "en",
    ) -> None:
        """Initialize Whisper provider.
        
        Args:
            model: Whisper model name.
            language: Language code (e.g., "en") or None for auto-detect.
        """
        self._model = model
        self._language = language
        self._client = AsyncOpenAI()
    
    @property
    def sample_rate(self) -> int:
        return 24000  # Match OpenAI Realtime API
    
    @property
    def supported_formats(self) -> list[str]:
        return ["wav", "mp3", "m4a", "webm", "mp4", "mpeg", "mpga", "oga", "ogg"]
    
    async def transcribe(self, audio: bytes) -> str:
        """Transcribe audio bytes.
        
        Args:
            audio: PCM16 audio bytes at 24kHz.
        
        Returns:
            Transcribed text.
        """
        # Convert PCM16 to WAV format for the API
        wav_buffer = self._pcm_to_wav(audio)
        
        # Create a file-like object for the API
        wav_buffer.seek(0)
        
        # Call Whisper API
        kwargs = {"model": self._model, "file": ("audio.wav", wav_buffer, "audio/wav")}
        if self._language:
            kwargs["language"] = self._language
        
        response = await self._client.audio.transcriptions.create(**kwargs)
        
        return response.text
    
    def _pcm_to_wav(self, pcm_data: bytes) -> io.BytesIO:
        """Convert PCM16 bytes to WAV format.
        
        Args:
            pcm_data: Raw PCM16 audio bytes.
        
        Returns:
            BytesIO containing WAV file data.
        """
        wav_buffer = io.BytesIO()
        
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm_data)
        
        wav_buffer.seek(0)
        return wav_buffer
    
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[str]:
        """Stream audio and transcribe.
        
        Note: Whisper API doesn't support true streaming, so we buffer
        and transcribe when we have enough audio (or stream ends).
        
        For true streaming, consider Deepgram or similar.
        """
        chunks = []
        total_bytes = 0
        
        async for chunk in audio_stream:
            chunks.append(chunk)
            total_bytes += len(chunk)
            
            # Transcribe every ~2 seconds of audio (96KB at 24kHz 16-bit mono)
            if total_bytes >= 96000:
                audio = b"".join(chunks)
                chunks = []
                total_bytes = 0
                
                transcript = await self.transcribe(audio)
                if transcript.strip():
                    yield transcript
        
        # Transcribe any remaining audio
        if chunks:
            audio = b"".join(chunks)
            transcript = await self.transcribe(audio)
            if transcript.strip():
                yield transcript

