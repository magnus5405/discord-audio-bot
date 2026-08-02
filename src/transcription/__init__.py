"""Transcription package.

Handles audio preprocessing, voice activity detection, and
speech-to-text via Google Cloud or local whisper.cpp.
"""

from .coordinator import PerUserTranscriptionCoordinator
from .preprocessing import convert_to_linear16, get_audio_duration, to_mono
from .stt import GoogleSTTClient, STTClient, create_stt_client
from .vad import VADProcessor
from .whispercpp import WhisperCppSTTClient

__all__ = [
    "GoogleSTTClient",
    "STTClient",
    "WhisperCppSTTClient",
    "create_stt_client",
    "convert_to_linear16",
    "to_mono",
    "get_audio_duration",
    "VADProcessor",
    "PerUserTranscriptionCoordinator",
]
