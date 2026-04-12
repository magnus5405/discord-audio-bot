"""Transcription package.

Handles audio preprocessing, voice activity detection, and
speech-to-text via Google Cloud.
"""

from .coordinator import PerUserTranscriptionCoordinator
from .preprocessing import convert_to_linear16, get_audio_duration, to_mono
from .stt import GoogleSTTClient
from .vad import VADProcessor

__all__ = [
    "GoogleSTTClient",
    "convert_to_linear16",
    "to_mono",
    "get_audio_duration",
    "VADProcessor",
    "PerUserTranscriptionCoordinator",
]
