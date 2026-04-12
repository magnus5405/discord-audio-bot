"""Google Cloud Speech-to-Text v1 (legacy) streaming — API key only, no Cloud project resource path."""

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
from ..storage.settings import DEFAULT_STT_LANGUAGE_CODE
from .preprocessing import get_audio_duration

logger = logging.getLogger(__name__)


class GoogleSTTV1Client:
    """Streaming STT using the v1 API (works with typical Cloud API keys without a v2 recognizer path)."""

    def __init__(
        self,
        primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
        alternative_languages: Optional[list[str]] = None,
        api_key: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        model: str | None = None,
        client: speech_v1.SpeechAsyncClient | None = None,
    ) -> None:
        del project_id, location, model
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        self.primary_language = primary_language
        self.alternative_languages = alternative_languages or ["en-US"]
        self.api_key = (api_key or os.getenv("GOOGLE_STT_API_KEY") or "").strip() or None
        if not self.api_key:
            raise ValueError(
                "Speech v1 requires GOOGLE_STT_API_KEY (a Google Cloud API key with "
                "Cloud Speech-to-Text enabled)."
            )
        self.client = client or speech_v1.SpeechAsyncClient(
            client_options=ClientOptions(api_key=self.api_key),
        )
        logger.info(
            "GoogleSTTV1Client (legacy v1): %s + %s",
            primary_language,
            self.alternative_languages,
        )

    def _build_recognition_config(self, sample_rate_hz: int) -> speech_v1.RecognitionConfig:
        return speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate_hz,
            language_code=self.primary_language,
            alternative_language_codes=self.alternative_languages,
            enable_automatic_punctuation=True,
        )

    def _build_streaming_config(self, sample_rate_hz: int) -> speech_v1.StreamingRecognitionConfig:
        return speech_v1.StreamingRecognitionConfig(
            config=self._build_recognition_config(sample_rate_hz),
            interim_results=False,
        )

    async def validate_connectivity(self) -> None:
        silence_bytes = b"\x00\x00" * 1600
        await self.client.recognize(
            config=self._build_recognition_config(16000),
            audio=speech_v1.RecognitionAudio(content=silence_bytes),
        )
        logger.info("Google STT (v1) connectivity check succeeded.")

    @staticmethod
    def _result_end_seconds(result: object) -> float:
        duration = getattr(result, "result_end_offset", None) or getattr(result, "result_end_time", None)
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
            end_offset = self._result_end_seconds(result)
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
        logger.debug("Stream recognition (v1) started for %s (%s)", username, user_id)
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
                end_offset = self._result_end_seconds(result)
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
                "Streaming STT (v1) returned no final results for %s (%s) after %s chunks "
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
                "Batch STT (v1) fallback recovered %s segment(s) for %s (%s).",
                len(fallback_segments),
                username,
                user_id,
            )
            for segment in fallback_segments:
                yield segment
            return
        logger.warning(
            "No transcription results (v1) for %s (%s) after %.2fs of audio.",
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
        segments = await self._recognize_with_batch(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            sample_rate_hz=sample_rate_hz,
            utterance_started_at=(time.time() if utterance_started_at is None else utterance_started_at),
        )
        return segments[-1] if segments else None
