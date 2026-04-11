"""Discord voice playback using VoiceClient."""

import asyncio
import logging
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
        logger.info("VoicePlaybackManager initialized")

    async def play_audio(self, audio_source: discord.AudioSource) -> None:
        """
        Play audio into voice channel and wait for completion.

        Args:
            audio_source: AudioSource to play (e.g., FFmpegAudio for MP3)
        """
        if self.is_speaking:
            logger.warning("Already speaking, skipping playback")
            return

        self.is_speaking = True
        self._playback_done_event = asyncio.Event()

        def on_complete(error: Optional[Exception]) -> None:
            """Called when playback finishes."""
            if error:
                logger.error(f"Playback error: {error}")
            self.is_speaking = False
            if self._playback_done_event:
                self._playback_done_event.set()
            logger.debug("Playback completed")

        try:
            logger.debug("Starting audio playback")
            self.voice_client.play(audio_source, after=on_complete)

            if self._playback_done_event:
                await self._playback_done_event.wait()
        except Exception as e:
            logger.error(f"Failed to play audio: {e}", exc_info=True)
            self.is_speaking = False
            raise

    async def stop_playback(self) -> None:
        """Stop current playback."""
        if self.voice_client.is_playing():
            self.voice_client.stop()
            logger.debug("Playback stopped")

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self.voice_client.is_playing() or self.is_speaking
