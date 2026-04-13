"""Tests for consent storage, audio gating, and transcript scrubbing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.discord.voice_sink import DiscordAudioSink
from src.models import AudioFrame, TranscriptSegment
from src.storage.consent import ConsentStore
from src.storage.transcripts import (
    TranscriptSessionWriter,
    attach_active_transcript_writer,
    detach_active_transcript_writer,
    scrub_user_data_from_transcripts,
)


def test_consent_store_accept_revoke_roundtrip(tmp_path: Path) -> None:
    store = ConsentStore(path=tmp_path / "consent" / "records.json")
    assert store.is_consented(42) is False

    store.record_acceptance(
        42,
        disclosure_dm_channel_id=100,
        disclosure_message_id=200,
        at="2020-01-01T00:00:00+00:00",
    )
    assert store.is_consented(42) is True
    last = store.last_accept(42)
    assert last is not None
    assert last.disclosure_message_id == 200

    assert store.revoke(42) is True
    assert store.is_consented(42) is False

    assert store.revoke(42) is False


def test_discord_audio_sink_drops_disallowed_users() -> None:
    async def scenario() -> None:
        queue: asyncio.Queue[AudioFrame] = asyncio.Queue()
        sink = DiscordAudioSink(
            audio_queue=queue,
            loop=asyncio.get_running_loop(),
            use_opus=False,
            user_audio_allowed=lambda uid: uid == 7,
        )
        allowed_user = type("U", (), {"id": 7, "display_name": "A", "name": "a"})()
        blocked_user = type("U", (), {"id": 8, "display_name": "B", "name": "b"})()
        pcm = b"\x00\x01" * 192
        sink.write(allowed_user, type("VD", (), {"pcm": pcm, "opus": b""})())
        sink.write(blocked_user, type("VD", (), {"pcm": pcm, "opus": b""})())

        await asyncio.sleep(0)
        assert queue.qsize() == 1
        frame = await queue.get()
        assert frame.user_id == 7

    asyncio.run(scenario())


def test_scrub_purges_active_transcript_writer_before_disk(tmp_path: Path) -> None:
    writer = TranscriptSessionWriter(
        guild_id=1,
        guild_name="G",
        channel_id=2,
        channel_name="C",
        transcripts_dir=tmp_path,
    )
    writer.segments.append(
        TranscriptSegment(
            user_id=10,
            username="a",
            text="keep other",
            start_ts=0.0,
            end_ts=1.0,
            is_final=True,
        )
    )
    writer.segments.append(
        TranscriptSegment(
            user_id=20,
            username="b",
            text="delete me",
            start_ts=0.0,
            end_ts=1.0,
            is_final=True,
        )
    )
    writer.write_snapshot()
    attach_active_transcript_writer(writer)
    try:
        stats = scrub_user_data_from_transcripts(tmp_path, 20)
        assert stats.segments_removed >= 1
        data = json.loads(writer.path.read_text(encoding="utf-8"))
        assert all(s.get("user_id") != 20 for s in data["segments"])
    finally:
        detach_active_transcript_writer(writer)


def test_scrub_user_data_from_transcripts(tmp_path: Path) -> None:
    session = {
        "session_started_at": "2020-01-01T00:00:00+00:00",
        "guild_id": 1,
        "guild_name": "G",
        "channel_id": 2,
        "channel_name": "C",
        "segments": [
            {"user_id": 10, "username": "a", "text": "x", "start_ts": 0.0, "end_ts": 1.0, "is_final": True},
            {"user_id": 20, "username": "b", "text": "y", "start_ts": 0.0, "end_ts": 1.0, "is_final": True},
        ],
        "bot_replies": [],
        "usage": {},
    }
    path = tmp_path / "2020-01-01_000000_G_C.json"
    path.write_text(json.dumps(session), encoding="utf-8")

    stats = scrub_user_data_from_transcripts(tmp_path, 10)
    assert stats.files_touched == 1
    assert stats.segments_removed == 1

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["segments"]) == 1
    assert data["segments"][0]["user_id"] == 20
