"""Runtime checks for Discord voice playback."""

from __future__ import annotations

import shutil
from pathlib import Path

from discord.voice_client import has_nacl
from discord.voice_state import has_dave


class PreflightError(RuntimeError):
    """Raised when a required runtime dependency is missing."""


def validate_voice_runtime(audio_path: Path) -> Path:
    """Validate local dependencies required for phase-one voice playback."""
    resolved_path = audio_path.expanduser()

    if shutil.which("ffmpeg") is None:
        raise PreflightError("FFmpeg was not found on PATH.")

    if not has_nacl:
        raise PreflightError("PyNaCl is required for Discord voice playback.")

    if not has_dave:
        raise PreflightError("The davey package is required for Discord voice playback.")

    if not resolved_path.exists():
        raise PreflightError(f"Audio file was not found: {resolved_path}")

    if not resolved_path.is_file():
        raise PreflightError(f"Audio path is not a file: {resolved_path}")

    return resolved_path.resolve()
