"""Google Cloud Speech-to-Text streaming transcription."""

import logging
from typing import AsyncIterator, Optional, List

from google.cloud import speech_v1

from ..models import TranscriptSegment

logger = logging.getLogger(__name__)


class GoogleSTTClient:
    """
    Streaming Speech-to-Text client using Google Cloud API.

    Uses gRPC streaming for real-time transcription.
    Supports multi-language with primary + alternative languages.

    Phase 3: STT integration
    """

    def __init__(
        self,
        primary_language: str = "da-DK",
        alternative_languages: Optional[List[str]] = None,
    ) -> None:
        """
        Initialize STT client.

        Args:
            primary_language: Primary language code (e.g., "da-DK")
            alternative_languages: List of alternative language codes
        """
        self.primary_language = primary_language
        self.alternative_languages = alternative_languages or ["en-US"]
        self.client = speech_v1.SpeechClient()
        logger.info(
            f"GoogleSTTClient initialized: {primary_language} "
            f"+ {self.alternative_languages}"
        )

    async def stream_recognize(
        self,
        audio_stream: AsyncIterator[bytes],
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
    ) -> AsyncIterator[TranscriptSegment]:
        """
        Stream audio and yield transcript segments as they arrive.

        Phase 3: STT integration

        Args:
            audio_stream: Async iterator of PCM audio bytes
            user_id: Discord user ID
            username: Discord username
            sample_rate_hz: Sample rate of audio

        Yields:
            TranscriptSegment as final results arrive
        """
        logger.debug(f"Stream recognition started for {username} ({user_id})")

    async def recognize_batch(
        self,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
    ) -> Optional[TranscriptSegment]:
        """
        Recognize audio from a batch/chunk.

        Args:
            audio_bytes: PCM audio data
            user_id: Discord user ID
            username: Discord username
            sample_rate_hz: Sample rate

        Returns:
            TranscriptSegment if recognized, None otherwise
        """
        logger.debug(f"Batch recognition for {username} ({user_id})")
        return None
