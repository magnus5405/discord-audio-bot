"""Tests for ElevenLabs TTS client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.models import Persona
from src.storage.transcripts import TranscriptSessionWriter
from src.tts.elevenlabs import ElevenLabsTTSClient, resolve_elevenlabs_api_key_from_env


def _persona() -> Persona:
    return Persona(
        persona_id="p1",
        display_name="Test Persona",
        system_instruction="Be brief.",
        genai_model="gemini-2.5-flash",
        elevenlabs_voice_id="voice_test_99",
    )


@pytest.mark.asyncio
async def test_api_key_is_stripped_for_request_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["xi"] = request.headers.get("xi-api-key", "")
        return httpx.Response(200, content=b"x")

    transport = httpx.MockTransport(handler)
    client = ElevenLabsTTSClient('  "mykey"  ', http_transport=transport)
    path = await client.synthesize_to_file("t", _persona())
    try:
        assert seen["xi"] == "mykey"
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_synthesize_to_file_posts_expected_request_and_writes_bytes(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.method == "POST"
        assert request.url.path.endswith("/text-to-speech/voice_test_99/stream")
        assert request.headers.get("xi-api-key") == "test-api-key"
        assert request.url.params.get("output_format") == "mp3_44100_128"
        body = json.loads(request.content.decode("utf-8"))
        assert body["text"] == "Hello from the test."
        assert body["model_id"] == "eleven_multilingual_v2"
        return httpx.Response(200, content=b"\xff\xfb" + b"\x00" * 200)

    transport = httpx.MockTransport(handler)
    client = ElevenLabsTTSClient("test-api-key", http_transport=transport)
    out_path = await client.synthesize_to_file("Hello from the test.", _persona())
    try:
        data = Path(out_path).read_bytes()
        assert len(data) == len(b"\xff\xfb" + b"\x00" * 200)
        assert len(captured) == 1
    finally:
        Path(out_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_stream_synthesize_yields_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abc" + b"def")

    transport = httpx.MockTransport(handler)
    client = ElevenLabsTTSClient("k", http_transport=transport)
    chunks = []
    async for part in client.stream_synthesize("x", _persona()):
        chunks.append(part)
    assert b"".join(chunks) == b"abcdef"


@pytest.mark.asyncio
async def test_http_error_propagates() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="server boom"))
    client = ElevenLabsTTSClient("bad-key", http_transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        await client.synthesize_to_file("text", _persona())


@pytest.mark.asyncio
async def test_401_raises_runtime_error_with_hint() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "nope"}))
    client = ElevenLabsTTSClient("bad-key", http_transport=transport)
    with pytest.raises(RuntimeError, match="ElevenLabs API rejected"):
        await client.synthesize_to_file("text", _persona())


@pytest.mark.asyncio
async def test_custom_model_id_constructor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["model_id"] == "custom_model_x"
        return httpx.Response(200, content=b"mp3")

    transport = httpx.MockTransport(handler)
    client = ElevenLabsTTSClient("k", model_id="custom_model_x", http_transport=transport)
    path = await client.synthesize_to_file("t", _persona())
    try:
        assert len(requests) == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_resolve_elevenlabs_api_key_prefers_primary_env_and_strips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "  primary  ")
    monkeypatch.setenv("ELEVEN_API_KEY", "ignored")
    assert resolve_elevenlabs_api_key_from_env() == "primary"


def test_resolve_elevenlabs_api_key_falls_back_to_eleven_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("ELEVEN_API_KEY", "fallback-key")
    assert resolve_elevenlabs_api_key_from_env() == "fallback-key"


def test_resolve_elevenlabs_api_key_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVEN_API_KEY", raising=False)
    assert resolve_elevenlabs_api_key_from_env() is None


def test_elevenlabs_client_record_tts_characters() -> None:
    client = ElevenLabsTTSClient("k", http_transport=None)
    client.record_tts_characters(50)
    client.record_tts_characters(25)
    assert client.total_characters_synthesized == 75


def test_transcript_writer_add_tts_characters_accumulates(tmp_path: Path) -> None:
    writer = TranscriptSessionWriter(
        guild_id=1,
        guild_name="g",
        channel_id=2,
        channel_name="c",
        transcripts_dir=tmp_path,
    )
    writer.add_tts_characters(120)
    writer.add_tts_characters(30)
    assert int(writer.usage["tts_characters"]) == 150


def test_transcript_writer_add_tts_seconds_accumulates(tmp_path: Path) -> None:
    writer = TranscriptSessionWriter(
        guild_id=1,
        guild_name="G",
        channel_id=2,
        channel_name="C",
        transcripts_dir=tmp_path,
    )
    writer.add_tts_seconds(1.25)
    assert writer.usage["tts_seconds_generated"] == pytest.approx(1.25)
    writer.add_tts_seconds(0.75)
    assert writer.usage["tts_seconds_generated"] == pytest.approx(2.0)
