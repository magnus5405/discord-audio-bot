"""Runtime checks for Discord voice dependencies and playback."""

from __future__ import annotations

from pathlib import Path

from discord.voice_client import has_nacl
from discord.voice_state import has_dave

from ..runtime_ffmpeg import resolve_ffmpeg_executable


class PreflightError(RuntimeError):
    """Raised when a required runtime dependency is missing."""


def validate_voice_dependencies() -> None:
    """Validate runtime dependencies required for Discord voice connectivity."""
    if not has_nacl:
        raise PreflightError("PyNaCl is required for Discord voice playback.")

    if not has_dave:
        raise PreflightError("The davey package is required for Discord voice playback.")


def validate_voice_runtime(audio_path: Path) -> Path:
    """Validate local dependencies required for voice playback from a file."""
    resolved_path = audio_path.expanduser()
    validate_voice_dependencies()

    try:
        resolve_ffmpeg_executable()
    except FileNotFoundError as exc:
        raise PreflightError(str(exc)) from exc

    if not resolved_path.exists():
        raise PreflightError(f"Audio file was not found: {resolved_path}")

    if not resolved_path.is_file():
        raise PreflightError(f"Audio path is not a file: {resolved_path}")

    return resolved_path.resolve()
