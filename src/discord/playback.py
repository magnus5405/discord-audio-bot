"""Discord voice playback using VoiceClient."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import discord

logger = logging.getLogger(__name__)


class VoicePlaybackManager:
    """
    Manages audio playback into Discord voice channels.

    Uses VoiceClient.play() with FFmpeg-based AudioSource.
    Handles playback completion events and "speaking mode" state.

    Phase 1: Voice connectivity + playback
    """

    def __init__(self, voice_client: discord.VoiceClient) -> None:
        """
        Initialize playback manager.

        Args:
            voice_client: Discord VoiceClient connected to channel
        """
        self.voice_client = voice_client
        self.is_speaking = False
        self._playback_done_event: Optional[asyncio.Event] = None
        self._playback_error: Optional[Exception] = None
        logger.info("VoicePlaybackManager initialized")

    def _finish_playback(self, error: Optional[Exception]) -> None:
        """Finalize playback state on the asyncio loop."""
        self.is_speaking = False
        self._playback_error = error
        if self._playback_done_event and not self._playback_done_event.is_set():
            self._playback_done_event.set()

    async def play_audio(self, audio_source: discord.AudioSource) -> None:
        """
        Play audio into voice channel and wait for completion.

        Args:
            audio_source: AudioSource to play (e.g., FFmpegAudio for MP3)
        """
        if self.is_playing():
            raise RuntimeError("Playback already in progress.")

        loop = asyncio.get_running_loop()
        self.is_speaking = True
        self._playback_error = None
        self._playback_done_event = asyncio.Event()

        def on_complete(error: Optional[Exception]) -> None:
            """Called when playback finishes."""
            loop.call_soon_threadsafe(self._finish_playback, error)

        try:
            logger.debug("Starting audio playback")
            self.voice_client.play(audio_source, after=on_complete)
            await self._playback_done_event.wait()
        except Exception as exc:
            self._finish_playback(None)
            logger.error("Failed to play audio: %s", exc, exc_info=True)
            raise RuntimeError("Failed to start audio playback.") from exc
        finally:
            self._playback_done_event = None

        if self._playback_error is not None:
            error = self._playback_error
            self._playback_error = None
            raise RuntimeError("Playback failed.") from error

    async def play_file(self, audio_path: Path) -> None:
        """Create an FFmpegOpusAudio source from a file path and play it."""
        logger.info("Playing audio file %s", audio_path)
        audio_source = discord.FFmpegOpusAudio(str(audio_path))
        await self.play_audio(audio_source)

    async def stop_playback(self) -> None:
        """Stop current playback."""
        if not self.is_playing():
            return

        if self.voice_client.is_playing():
            self.voice_client.stop()

        self._finish_playback(None)
        logger.debug("Playback stopped")

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self.voice_client.is_playing() or self.is_speaking
