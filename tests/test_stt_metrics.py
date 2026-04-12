"""STT audio duration accounting (LINEAR16 mono)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.storage.transcripts import TranscriptSessionWriter


def test_linear16_mono_duration_from_byte_length() -> None:
    """Bytes sent to STT at 16 kHz mono: duration = len / (2 * sample_rate)."""
    sample_rate_hz = 16000
    for expected in (0.05, 0.1, 1.0):
        byte_len = int(expected * 2 * sample_rate_hz)
        delta = byte_len / (2.0 * float(sample_rate_hz))
        assert abs(delta - expected) < 1e-6


def test_transcript_writer_accumulates_stt_seconds(tmp_path: Path) -> None:
    writer = TranscriptSessionWriter(
        guild_id=1,
        guild_name="g",
        channel_id=2,
        channel_name="c",
        transcripts_dir=tmp_path,
        session_started_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    writer.add_stt_seconds(1.25)
    writer.add_stt_seconds(0.25)
    assert float(writer.usage["stt_seconds_processed"]) == 1.5
