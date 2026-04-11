"""ElevenLabs text-to-speech client."""

import logging
import tempfile
from typing import AsyncIterator, Optional

from ..models import Persona

logger = logging.getLogger(__name__)


class ElevenLabsTTSClient:
    """
    ElevenLabs streaming text-to-speech client.

    Generates audio via streaming endpoint, supports MP3 output.
    Tracks per-session voice generation duration.

    Phase 5: ElevenLabs TTS + playback
    """

    def __init__(self, api_key: str) -> None:
        """
        Initialize ElevenLabs client.

        Args:
            api_key: ElevenLabs API key (used as xi-api-key header)
        """
        self.api_key = api_key
        self.total_seconds_generated = 0.0
        logger.info("ElevenLabsTTSClient initialized")

    async def stream_synthesize(
        self, text: str, persona: Persona, output_format: str = "mp3_44100_128"
    ) -> AsyncIterator[bytes]:
        """
        Stream synthesized audio as it is generated.

        Phase 5: TTS streaming

        Args:
            text: Text to synthesize
            persona: Persona with voice_id
            output_format: Output format

        Yields:
            Chunks of audio data
        """
        logger.debug(f"Streaming TTS for persona '{persona.display_name}'")

    async def synthesize_to_file(
        self, text: str, persona: Persona, output_format: str = "mp3_44100_128"
    ) -> str:
        """
        Synthesize audio and save to temporary file.

        Args:
            text: Text to synthesize
            persona: Persona configuration
            output_format: Output format

        Returns:
            Path to temporary MP3 file
        """
        logger.debug(f"TTS synthesis to file: {text[:50]}...")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = f.name

        return temp_path

    def record_tts_duration(self, duration_seconds: float) -> None:
        """Record voice generation duration for session tracking."""
        self.total_seconds_generated += duration_seconds
        logger.debug(
            f"TTS duration recorded: +{duration_seconds:.1f}s "
            f"(total: {self.total_seconds_generated:.1f}s)"
        )

    async def get_account_usage(self) -> Optional[dict]:
        """Get account-level character/voice usage statistics."""
        logger.debug("Fetching ElevenLabs account usage stats...")
        return None
