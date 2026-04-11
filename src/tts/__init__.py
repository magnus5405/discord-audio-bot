"""Text-to-Speech package.

Handles audio synthesis via ElevenLabs and related voice generation.
"""

from .elevenlabs import ElevenLabsTTSClient

__all__ = ["ElevenLabsTTSClient"]
