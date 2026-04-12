"""Tests for phase-three transcription, preprocessing, and transcript storage."""

from __future__ import annotations

import asyncio
import json
from array import array
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.models import AudioFrame, TranscriptSegment
from src.storage.transcripts import TranscriptSessionWriter
from src.transcription.coordinator import PerUserTranscriptionCoordinator
from src.transcription.preprocessing import convert_to_linear16, get_audio_duration, to_mono
from src.transcription.stt import GoogleSTTClient


def run_async(awaitable):
    """Run an awaitable in a dedicated event loop for plain pytest."""
    return asyncio.run(awaitable)


class FakeAsyncResponses:
    """Async iterable wrapper for mocked streaming responses."""

    def __init__(self, responses):
        self._responses = responses

    def __aiter__(self):
        self._iterator = iter(self._responses)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeSpeechAsyncClient:
    """Mock Google Speech async client."""

    def __init__(self, responses, *, batch_response=None):
        self.responses = responses
        self.batch_response = batch_response or SimpleNamespace(results=[])
        self.requests = []
        self.recognize_calls: list[dict[str, object]] = []

    async def streaming_recognize(self, *, requests, **_kwargs):
        async for request in requests:
            self.requests.append(request)
        return FakeAsyncResponses(self.responses)

    async def recognize(self, *, config, audio, **_kwargs):
        self.recognize_calls.append({"config": config, "audio": audio})
        return self.batch_response


class FakeCoordinatorSTTClient:
    """Fake STT client that emits one final segment per utterance."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def stream_recognize(
        self,
        audio_stream,
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
    ):
        chunks = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        self.calls.append(
            {
                "user_id": user_id,
                "username": username,
                "sample_rate_hz": sample_rate_hz,
                "chunks": list(chunks),
            }
        )
        if chunks:
            yield TranscriptSegment(
                user_id=user_id,
                username=username,
                text=f"{username}:{len(chunks)}",
                start_ts=utterance_started_at or 0.0,
                end_ts=(utterance_started_at or 0.0) + 0.25,
                is_final=True,
                language_code="da-DK",
            )


def test_audio_preprocessing_downmixes_to_mono_and_reports_duration():
    """Stereo PCM should be downmixed to mono without changing the sample rate."""
    stereo_samples = array("h", [1000, 3000, -1000, 1000]).tobytes()

    mono_bytes = to_mono(stereo_samples, channels=2)
    converted_bytes = convert_to_linear16(
        stereo_samples,
        from_sample_rate=48000,
        to_sample_rate=48000,
        channels=2,
    )

    mono_samples = array("h")
    mono_samples.frombytes(mono_bytes)

    assert mono_samples.tolist() == [1000, -1000]
    assert converted_bytes == mono_bytes
    assert get_audio_duration(mono_bytes, sample_rate=2, channels=1) == 1.0


def test_audio_preprocessing_resamples_48k_mono_to_16k():
    """Resampling should decimate 48 kHz mono to 16 kHz by a factor of 3."""
    mono_48k = array("h", [0, 1, 2, 3, 4, 5]).tobytes()

    converted = convert_to_linear16(
        mono_48k,
        from_sample_rate=48000,
        to_sample_rate=16000,
        channels=1,
    )

    converted_samples = array("h")
    converted_samples.frombytes(converted)

    assert converted_samples.tolist() == [0, 3]


def test_google_stt_client_builds_streaming_requests_and_parses_final_results():
    """GoogleSTTClient should send config first and emit only final transcript segments."""

    async def scenario() -> None:
        fake_client = FakeSpeechAsyncClient(
            responses=[
                SimpleNamespace(
                    results=[
                        SimpleNamespace(
                            is_final=False,
                            alternatives=[SimpleNamespace(transcript="ignore me")],
                            result_end_time=SimpleNamespace(seconds=0, nanos=500_000_000),
                            language_code="da-DK",
                        )
                    ]
                ),
                SimpleNamespace(
                    results=[
                        SimpleNamespace(
                            is_final=True,
                            alternatives=[SimpleNamespace(transcript="Hej verden")],
                            result_end_time=SimpleNamespace(seconds=1, nanos=500_000_000),
                            language_code="da-DK",
                        ),
                        SimpleNamespace(
                            is_final=True,
                            alternatives=[SimpleNamespace(transcript="How are you?")],
                            result_end_time=SimpleNamespace(seconds=2, nanos=250_000_000),
                            language_code="en-US",
                        ),
                    ]
                ),
            ]
        )
        stt_client = GoogleSTTClient(
            primary_language="da-DK",
            alternative_languages=["en-US"],
            api_key="stt-api-key",
            client=fake_client,
        )

        async def audio_stream():
            yield b"chunk-1"
            yield b"chunk-2"

        segments = [
            segment
            async for segment in stt_client.stream_recognize(
                audio_stream=audio_stream(),
                user_id=123,
                username="Alice",
                sample_rate_hz=48000,
                utterance_started_at=100.0,
            )
        ]

        assert len(fake_client.requests) == 3
        config_request = fake_client.requests[0]
        assert config_request.streaming_config.config.encoding.name == "LINEAR16"
        assert config_request.streaming_config.config.sample_rate_hertz == 48000
        assert config_request.streaming_config.config.language_code == "da-DK"
        assert list(config_request.streaming_config.config.alternative_language_codes) == ["en-US"]
        assert config_request.streaming_config.interim_results is False
        assert [request.audio_content for request in fake_client.requests[1:]] == [b"chunk-1", b"chunk-2"]

        assert [segment.text for segment in segments] == ["Hej verden", "How are you?"]
        assert segments[0].start_ts == 100.0
        assert segments[0].end_ts == 101.5
        assert segments[0].language_code == "da-DK"
        assert segments[1].start_ts == 101.5
        assert segments[1].end_ts == 102.25
        assert segments[1].language_code == "en-US"

    run_async(scenario())


def test_google_stt_client_falls_back_to_batch_when_streaming_returns_no_final_results():
    """Streaming STT should retry with batch recognition when the stream closes empty."""

    async def scenario() -> None:
        fake_client = FakeSpeechAsyncClient(
            responses=[SimpleNamespace(results=[])],
            batch_response=SimpleNamespace(
                results=[
                    SimpleNamespace(
                        alternatives=[SimpleNamespace(transcript="fallback transcript")],
                        result_end_time=SimpleNamespace(seconds=0, nanos=750_000_000),
                        language_code="da-DK",
                    )
                ]
            ),
        )
        stt_client = GoogleSTTClient(
            primary_language="da-DK",
            alternative_languages=["en-US"],
            api_key="stt-api-key",
            client=fake_client,
        )

        async def audio_stream():
            yield b"chunk-1"
            yield b"chunk-2"

        segments = [
            segment
            async for segment in stt_client.stream_recognize(
                audio_stream=audio_stream(),
                user_id=123,
                username="Alice",
                sample_rate_hz=48000,
                utterance_started_at=200.0,
            )
        ]

        assert [segment.text for segment in segments] == ["fallback transcript"]
        assert segments[0].start_ts == 200.0
        assert segments[0].end_ts == 200.75
        assert len(fake_client.recognize_calls) == 1
        assert fake_client.recognize_calls[0]["audio"].content == b"chunk-1chunk-2"

    run_async(scenario())


def test_google_stt_client_uses_explicit_api_key(monkeypatch):
    """A dedicated STT API key should be passed to the Google client options."""
    created_clients: list[object] = []

    class FakeAsyncClient:
        def __init__(self, *, client_options=None):
            self.client_options = client_options
            created_clients.append(self)

    monkeypatch.setenv("GOOGLE_STT_API_KEY", "stt-api-key-from-env")
    with patch("src.transcription.stt.speech_v1.SpeechAsyncClient", FakeAsyncClient):
        stt_client = GoogleSTTClient(primary_language="da-DK")

    assert stt_client.api_key == "stt-api-key-from-env"
    assert created_clients[0].client_options.api_key == "stt-api-key-from-env"


def test_google_stt_client_raises_clear_error_when_no_credentials(monkeypatch):
    """Missing STT API keys should raise an actionable error message."""
    monkeypatch.delenv("GOOGLE_STT_API_KEY", raising=False)

    try:
        GoogleSTTClient(primary_language="da-DK")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected GoogleSTTClient to raise ValueError")

    assert "GOOGLE_STT_API_KEY" in message


def test_transcription_coordinator_keeps_users_separate_and_splits_on_idle_gap():
    """Per-user utterance coordination should isolate speakers and rotate on idle gaps."""

    async def scenario() -> None:
        fake_stt_client = FakeCoordinatorSTTClient()
        handled_segments: list[TranscriptSegment] = []
        coordinator = PerUserTranscriptionCoordinator(
            stt_client=fake_stt_client,
            segment_handler=handled_segments.append,
            idle_timeout_seconds=0.5,
        )
        pcm_bytes = array("h", [2, 4, 6, 8]).tobytes()

        await coordinator.process_frame(
            AudioFrame(
                user_id=1,
                username="Alice",
                pcm_bytes=pcm_bytes,
                sample_rate_hz=48000,
                channels=2,
                timestamp_monotonic=1.0,
            )
        )
        await coordinator.process_frame(
            AudioFrame(
                user_id=1,
                username="Alice",
                pcm_bytes=pcm_bytes,
                sample_rate_hz=48000,
                channels=2,
                timestamp_monotonic=1.2,
            )
        )
        await coordinator.process_frame(
            AudioFrame(
                user_id=2,
                username="Bob",
                pcm_bytes=pcm_bytes,
                sample_rate_hz=48000,
                channels=2,
                timestamp_monotonic=1.3,
            )
        )
        await coordinator.process_frame(
            AudioFrame(
                user_id=1,
                username="Alice",
                pcm_bytes=pcm_bytes,
                sample_rate_hz=48000,
                channels=2,
                timestamp_monotonic=1.8,
            )
        )
        await coordinator._close_idle_sessions(reference_monotonic=2.5)
        await coordinator.shutdown()

        assert len(fake_stt_client.calls) == 3
        call_summaries = sorted(
            (call["user_id"], call["username"], len(call["chunks"]))
            for call in fake_stt_client.calls
        )
        assert call_summaries == [
            (1, "Alice", 1),
            (1, "Alice", 2),
            (2, "Bob", 1),
        ]
        assert sorted(segment.text for segment in handled_segments) == ["Alice:1", "Alice:2", "Bob:1"]

    run_async(scenario())


def test_transcript_session_writer_rewrites_valid_session_json(tmp_path):
    """Session transcript snapshots should be rewritten atomically as segments arrive."""
    writer = TranscriptSessionWriter(
        guild_id=1,
        guild_name="Guild Name",
        channel_id=2,
        channel_name="Main Lobby",
        transcripts_dir=tmp_path,
        session_started_at=datetime(2026, 4, 11, 20, 30, tzinfo=timezone.utc),
    )

    first_segment = TranscriptSegment(
        user_id=2,
        username="Bob",
        text="Second line",
        start_ts=2.0,
        end_ts=3.0,
        is_final=True,
        language_code="en-US",
    )
    second_segment = TranscriptSegment(
        user_id=1,
        username="Alice",
        text="First line",
        start_ts=1.0,
        end_ts=2.0,
        is_final=True,
        language_code="da-DK",
    )

    writer.add_segment(first_segment)
    writer.add_segment(second_segment)

    assert writer.path.exists()
    payload = json.loads(writer.path.read_text(encoding="utf-8"))

    assert payload["session_started_at"] == "2026-04-11T20:30:00+00:00"
    assert payload["guild_name"] == "Guild Name"
    assert payload["channel_name"] == "Main Lobby"
    assert [segment["username"] for segment in payload["segments"]] == ["Alice", "Bob"]
    assert payload["bot_replies"] == []
    assert payload["usage"] == {"total_tokens": 0, "tts_seconds_generated": 0.0}
