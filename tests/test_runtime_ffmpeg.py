"""Tests for FFmpeg runtime helpers."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import src.runtime_ffmpeg as runtime_ffmpeg


def test_probe_audio_duration_seconds_async_runs_in_worker_thread(monkeypatch) -> None:
    """Duration probing should hop to a worker thread instead of blocking the event loop."""
    seen: dict[str, object] = {}

    def fake_probe(path: Path) -> float:
        seen["path"] = path
        seen["thread_id"] = threading.get_ident()
        return 1.25

    monkeypatch.setattr(runtime_ffmpeg, "probe_audio_duration_seconds", fake_probe)

    async def scenario() -> tuple[int, float]:
        loop_thread_id = threading.get_ident()
        duration = await runtime_ffmpeg.probe_audio_duration_seconds_async(Path("clip.mp3"))
        return loop_thread_id, duration

    loop_thread_id, duration = asyncio.run(scenario())

    assert seen["path"] == Path("clip.mp3")
    assert seen["thread_id"] != loop_thread_id
    assert duration == 1.25
