"""Text-to-Speech package.

Handles audio synthesis via ElevenLabs and related voice generation.
"""

from .elevenlabs import ElevenLabsTTSClient, resolve_elevenlabs_api_key_from_env

__all__ = ["ElevenLabsTTSClient", "resolve_elevenlabs_api_key_from_env"]
