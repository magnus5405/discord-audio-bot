"""Resolve FFmpeg (and ffprobe) for discord.py playback and pydub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .runtime_dirs import app_bundle_dir

logger = logging.getLogger(__name__)

_ffmpeg_cached: str | None = None
_ffprobe_resolved = False
_ffprobe_cached: str | None = None
_pydub_configured = False
_FFPROBE_DURATION_TIMEOUT_SECONDS = 15
_FFMPEG_DURATION_TIMEOUT_SECONDS = 30


def resolve_ffmpeg_executable() -> str:
    """Return path to ``ffmpeg`` (``ffmpeg.exe`` on Windows).

    Order: ``FFMPEG_PATH`` env, ``ffmpeg`` next to the frozen exe / cwd bundle, then ``PATH``.
    """
    global _ffmpeg_cached
    if _ffmpeg_cached is not None:
        return _ffmpeg_cached

    raw = (os.getenv("FFMPEG_PATH") or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file():
            _ffmpeg_cached = str(path.resolve())
            logger.debug("Using FFmpeg from FFMPEG_PATH: %s", _ffmpeg_cached)
            return _ffmpeg_cached
        raise FileNotFoundError(f"FFMPEG_PATH is set but is not a file: {raw}")

    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = app_bundle_dir() / exe_name
    if bundled.is_file():
        _ffmpeg_cached = str(bundled.resolve())
        logger.debug("Using bundled FFmpeg: %s", _ffmpeg_cached)
        return _ffmpeg_cached

    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_cached = found
        logger.debug("Using FFmpeg from PATH: %s", _ffmpeg_cached)
        return _ffmpeg_cached

    if getattr(sys, "frozen", False):
        raise FileNotFoundError(
            "ffmpeg not found next to the application. Reinstall or repair the distribution."
        )
    raise FileNotFoundError(
        "ffmpeg not found. Install FFmpeg and ensure it is on PATH, "
        "or set FFMPEG_PATH to the ffmpeg executable."
    )


def resolve_ffprobe_executable() -> str | None:
    """Return path to ``ffprobe`` if available, else ``None``.

    Prefer ``ffprobe`` next to the resolved ``ffmpeg``, then ``PATH``.
    """
    global _ffprobe_resolved, _ffprobe_cached
    if _ffprobe_resolved:
        return _ffprobe_cached
    _ffprobe_resolved = True

    ffmpeg = Path(resolve_ffmpeg_executable())
    probe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    probe = ffmpeg.parent / probe_name
    if probe.is_file():
        _ffprobe_cached = str(probe.resolve())
        logger.debug("Using ffprobe next to FFmpeg: %s", _ffprobe_cached)
        return _ffprobe_cached

    found = shutil.which("ffprobe")
    if found:
        _ffprobe_cached = found
        logger.debug("Using ffprobe from PATH: %s", _ffprobe_cached)
        return _ffprobe_cached

    _ffprobe_cached = None
    return None


def probe_audio_duration_seconds(path: Path | str) -> float:
    """Return audio duration in seconds using ffprobe, or FFmpeg stderr as fallback."""
    p = Path(path)
    ffprobe = resolve_ffprobe_executable()
    if ffprobe:
        try:
            out = subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(p),
                ],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_FFPROBE_DURATION_TIMEOUT_SECONDS,
            )
            data = json.loads(out)
            dur = data.get("format", {}).get("duration")
            if dur is not None:
                return float(dur)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("ffprobe duration probe failed for %s: %s", p, exc)

    ffmpeg = resolve_ffmpeg_executable()
    proc = subprocess.run(
        [ffmpeg, "-nostats", "-i", str(p), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_DURATION_TIMEOUT_SECONDS,
    )
    stderr = proc.stderr or ""
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
    if not match:
        raise RuntimeError(
            "Could not determine audio duration (ffprobe missing or failed, "
            "and ffmpeg did not report Duration in stderr). "
            "Install a full FFmpeg build with ffprobe, or ensure ffmpeg is on PATH."
        )
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


async def probe_audio_duration_seconds_async(path: Path | str) -> float:
    """Resolve audio duration in a worker thread so the UI loop stays responsive."""
    return await asyncio.to_thread(probe_audio_duration_seconds, path)


def configure_pydub_once() -> None:
    """Point pydub's AudioSegment at the same FFmpeg (and ffprobe if present)."""
    global _pydub_configured
    if _pydub_configured:
        return
    import pydub.utils as pydub_utils
    from pydub import AudioSegment

    ffmpeg = Path(resolve_ffmpeg_executable())
    AudioSegment.converter = str(ffmpeg)
    ffp = resolve_ffprobe_executable()
    if ffp:
        AudioSegment.ffprobe = ffp
        # pydub's mediainfo_json calls get_prober_name() (bare "ffprobe"), not AudioSegment.ffprobe.
        pydub_utils.get_prober_name = lambda: ffp  # type: ignore[method-assign]
    _pydub_configured = True
