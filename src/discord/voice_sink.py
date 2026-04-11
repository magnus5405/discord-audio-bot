"""Voice receive sink implementation for per-user audio capture."""

import asyncio
import logging
from typing import Optional

import discord
from discord.ext.voice_recv import AudioSink

from ..models import AudioFrame

logger = logging.getLogger(__name__)


class DiscordAudioSink(AudioSink):
    """
    Audio sink for receiving per-user audio frames from Discord voice.

    Forwards audio frames to async processing queue thread-safely.
    Minimal work in callback to avoid blocking receive thread.

    Phase 2: Voice receive plumbing
    """

    def __init__(self, audio_queue: asyncio.Queue) -> None:
        """
        Initialize audio sink.

        Args:
            audio_queue: Async queue to put AudioFrames into
        """
        self.audio_queue = audio_queue
        self.listening_enabled = True
        logger.info("DiscordAudioSink initialized")

    async def filter_audio(
        self, user: discord.User, audio: discord.AudioData
    ) -> Optional[discord.AudioData]:
        """Filter audio before sink processing."""
        if not self.listening_enabled:
            return None
        return audio

    async def post_audio(self, user: discord.User, audio: discord.AudioData) -> None:
        """Receive audio frame and forward to async queue."""
        if not self.listening_enabled:
            return

        try:
            frame = AudioFrame.new(user_id=user.id, pcm_bytes=audio.pcm)
            asyncio.run_coroutine_threadsafe(
                self.audio_queue.put(frame),
                self.audio_queue._loop
                if hasattr(self.audio_queue, "_loop")
                else asyncio.get_event_loop(),
            )
        except Exception as e:
            logger.error(f"Failed to queue audio frame from {user}: {e}")

    def pause_listening(self) -> None:
        """Stop accepting new audio frames (bot is speaking)."""
        self.listening_enabled = False
        logger.debug("Listening paused")

    def resume_listening(self) -> None:
        """Resume accepting audio frames."""
        self.listening_enabled = True
        logger.debug("Listening resumed")

    async def cleanup(self) -> None:
        """Clean up sink resources."""
        logger.debug("DiscordAudioSink cleanup")
