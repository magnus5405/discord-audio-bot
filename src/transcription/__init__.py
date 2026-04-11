"""Transcription package.

Handles audio preprocessing, voice activity detection, and
speech-to-text via Google Cloud.
"""

from .stt import GoogleSTTClient
from .preprocessing import convert_to_linear16, to_mono, get_audio_duration
from .vad import VADProcessor

__all__ = [
    "GoogleSTTClient",
    "convert_to_linear16",
    "to_mono",
    "get_audio_duration",
    "VADProcessor",
]
