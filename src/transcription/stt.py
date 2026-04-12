"""Google Cloud Speech-to-Text streaming transcription."""

from __future__ import annotations

import logging
import os
import time
from array import array
from collections.abc import AsyncIterator
from typing import Optional

from google.api_core.client_options import ClientOptions
from google.cloud import speech_v1

from ..models import TranscriptSegment
from .preprocessing import get_audio_duration

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
        alternative_languages: Optional[list[str]] = None,
        api_key: str | None = None,
        client: speech_v1.SpeechAsyncClient | None = None,
    ) -> None:
        """
        Initialize STT client.

        Args:
            primary_language: Primary language code (e.g., "da-DK")
            alternative_languages: List of alternative language codes
            api_key: Google Speech-to-Text API key. If omitted, the client reads
                `GOOGLE_STT_API_KEY` from the environment.
        """
        self.primary_language = primary_language
        self.alternative_languages = alternative_languages or ["en-US"]
        self.api_key = self._resolve_api_key(api_key)
        self.client = client or self._build_client()
        logger.info(
            "GoogleSTTClient initialized: %s + %s",
            primary_language,
            self.alternative_languages,
        )

    @staticmethod
    def _resolve_api_key(api_key: str | None) -> str:
        resolved_api_key = api_key or os.getenv("GOOGLE_STT_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "Google Speech-to-Text API key was not found. Set GOOGLE_STT_API_KEY in "
                "the environment or pass api_key explicitly."
            )

        return resolved_api_key

    def _build_client(self) -> speech_v1.SpeechAsyncClient:
        logger.info("GoogleSTTClient using API key authentication")
        return speech_v1.SpeechAsyncClient(
            client_options=ClientOptions(api_key=self.api_key),
        )

    def _build_streaming_config(
        self,
        sample_rate_hz: int,
    ) -> speech_v1.StreamingRecognitionConfig:
        recognition_config = self._build_recognition_config(sample_rate_hz)
        return speech_v1.StreamingRecognitionConfig(
            config=recognition_config,
            interim_results=False,
        )

    def _build_recognition_config(
        self,
        sample_rate_hz: int,
    ) -> speech_v1.RecognitionConfig:
        return speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate_hz,
            language_code=self.primary_language,
            alternative_language_codes=self.alternative_languages,
            enable_automatic_punctuation=True,
        )

    async def validate_connectivity(self) -> None:
        """Fail fast if STT credentials or API access are not usable."""
        # 100 ms of silence, 16-bit mono at 16 kHz.
        silence_bytes = b"\x00\x00" * 1600
        await self.client.recognize(
            config=self._build_recognition_config(16000),
            audio=speech_v1.RecognitionAudio(content=silence_bytes),
        )
        logger.info("Google STT connectivity check succeeded.")

    @staticmethod
    def _duration_seconds(duration: object | None) -> float:
        if duration is None:
            return 0.0

        seconds = getattr(duration, "seconds", 0) or 0
        nanos = getattr(duration, "nanos", 0) or 0
        return float(seconds) + (float(nanos) / 1_000_000_000.0)

    def _build_segment(
        self,
        *,
        user_id: int,
        username: str,
        transcript_text: str,
        utterance_start: float,
        start_offset: float,
        end_offset: float,
        language_code: str | None,
    ) -> TranscriptSegment:
        if end_offset <= start_offset:
            end_offset = start_offset

        return TranscriptSegment(
            user_id=user_id,
            username=username,
            text=transcript_text,
            start_ts=utterance_start + start_offset,
            end_ts=utterance_start + end_offset,
            is_final=True,
            language_code=language_code,
        )

    async def _recognize_with_batch(
        self,
        *,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int,
        utterance_started_at: float,
    ) -> list[TranscriptSegment]:
        if not audio_bytes:
            return []

        response = await self.client.recognize(
            config=self._build_recognition_config(sample_rate_hz),
            audio=speech_v1.RecognitionAudio(content=audio_bytes),
        )

        audio_duration_seconds = get_audio_duration(
            audio_bytes,
            sample_rate=sample_rate_hz,
            channels=1,
        )
        previous_end_offset = 0.0
        segments: list[TranscriptSegment] = []

        for result in getattr(response, "results", []):
            alternatives = getattr(result, "alternatives", [])
            if not alternatives:
                continue

            transcript_text = (alternatives[0].transcript or "").strip()
            if not transcript_text:
                continue

            end_offset = self._duration_seconds(getattr(result, "result_end_time", None))
            if end_offset <= 0.0:
                end_offset = audio_duration_seconds

            segment = self._build_segment(
                user_id=user_id,
                username=username,
                transcript_text=transcript_text,
                utterance_start=utterance_started_at,
                start_offset=previous_end_offset,
                end_offset=end_offset,
                language_code=getattr(result, "language_code", None) or None,
            )
            previous_end_offset = max(previous_end_offset, end_offset)
            segments.append(segment)

        return segments

    async def stream_recognize(
        self,
        audio_stream: AsyncIterator[bytes],
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
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
        logger.debug("Stream recognition started for %s (%s)", username, user_id)
        utterance_start = time.time() if utterance_started_at is None else utterance_started_at
        previous_end_offset = 0.0
        streaming_config = self._build_streaming_config(sample_rate_hz)
        audio_chunks: list[bytes] = []
        audio_chunk_count = 0
        total_audio_bytes = 0
        final_segment_count = 0

        async def requests() -> AsyncIterator[speech_v1.StreamingRecognizeRequest]:
            nonlocal audio_chunk_count, total_audio_bytes
            yield speech_v1.StreamingRecognizeRequest(streaming_config=streaming_config)
            async for audio_chunk in audio_stream:
                if audio_chunk:
                    audio_chunks.append(audio_chunk)
                    audio_chunk_count += 1
                    total_audio_bytes += len(audio_chunk)
                    yield speech_v1.StreamingRecognizeRequest(audio_content=audio_chunk)

        responses = await self.client.streaming_recognize(requests=requests())
        async for response in responses:
            for result in getattr(response, "results", []):
                if not getattr(result, "is_final", False):
                    continue

                alternatives = getattr(result, "alternatives", [])
                if not alternatives:
                    continue

                transcript_text = (alternatives[0].transcript or "").strip()
                if not transcript_text:
                    continue

                end_offset = self._duration_seconds(getattr(result, "result_end_time", None))
                segment = self._build_segment(
                    user_id=user_id,
                    username=username,
                    transcript_text=transcript_text,
                    utterance_start=utterance_start,
                    start_offset=previous_end_offset,
                    end_offset=end_offset,
                    language_code=getattr(result, "language_code", None) or None,
                )
                previous_end_offset = max(previous_end_offset, end_offset)
                final_segment_count += 1
                yield segment

        if final_segment_count > 0 or total_audio_bytes <= 0:
            return

        audio_bytes = b"".join(audio_chunks)
        audio_duration_seconds = get_audio_duration(
            audio_bytes,
            sample_rate=sample_rate_hz,
            channels=1,
        )
        rms_level = 0.0
        peak_level = 0
        if audio_bytes:
            samples = array("h")
            samples.frombytes(audio_bytes[: len(audio_bytes) - (len(audio_bytes) % 2)])
            if samples:
                peak_level = max(abs(sample) for sample in samples)
                rms_level = (
                    sum(float(sample) * float(sample) for sample in samples) / float(len(samples))
                ) ** 0.5
        logger.warning(
            (
                "Streaming STT returned no final results for %s (%s) after %s chunks "
                "(%.2fs audio, rms=%.1f, peak=%s). Retrying with batch recognition."
            ),
            username,
            user_id,
            audio_chunk_count,
            audio_duration_seconds,
            rms_level,
            peak_level,
        )

        fallback_segments = await self._recognize_with_batch(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            sample_rate_hz=sample_rate_hz,
            utterance_started_at=utterance_start,
        )
        if fallback_segments:
            logger.info(
                "Batch STT fallback recovered %s final segment(s) for %s (%s).",
                len(fallback_segments),
                username,
                user_id,
            )
            for segment in fallback_segments:
                yield segment
            return

        logger.warning(
            "No transcription results were produced for %s (%s) after %.2fs of audio.",
            username,
            user_id,
            audio_duration_seconds,
        )

    async def recognize_batch(
        self,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
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
        logger.debug("Batch recognition for %s (%s)", username, user_id)
        segments = await self._recognize_with_batch(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            sample_rate_hz=sample_rate_hz,
            utterance_started_at=(time.time() if utterance_started_at is None else utterance_started_at),
        )
        return segments[-1] if segments else None
