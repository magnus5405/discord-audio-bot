"""Voice receive sink implementation for per-user audio capture."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord.ext.voice_recv import AudioSink, VoiceData

from ..models import AudioFrame

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReceivedUserStats:
    """Track receive-window statistics for a single Discord user."""

    user_id: int
    display_name: str
    audio_chunk_count: int = 0
    speaking_start_count: int = 0
    speaking_stop_count: int = 0


class DiscordAudioSink(AudioSink):
    """
    Audio sink for validating Discord voice receive plumbing.

    The phase-two smoke runner defaults to Opus mode because it avoids the
    extension's PCM decode path, which can fail before we see speaker activity.
    Phase three can switch back to PCM mode when the transcription pipeline is
    ready to consume it.
    """

    def __init__(
        self,
        audio_queue: asyncio.Queue[AudioFrame],
        loop: asyncio.AbstractEventLoop,
        *,
        use_opus: bool = True,
    ) -> None:
        """Initialize the sink with a target queue, event loop, and audio mode."""
        super().__init__()
        self.audio_queue = audio_queue
        self.loop = loop
        self.use_opus = use_opus
        self._closed = False
        self._queue_full_logged = False
        self._user_stats: dict[int, ReceivedUserStats] = {}
        mode = "Opus" if use_opus else "PCM"
        logger.info("DiscordAudioSink initialized in %s mode", mode)

    def wants_opus(self) -> bool:
        """Tell discord-ext-voice-recv whether this sink wants raw Opus packets."""
        return self.use_opus

    def write(self, user: Optional[discord.User], data: VoiceData) -> None:
        """Receive one audio chunk from the extension and forward it safely."""
        if self._closed or user is None:
            return

        audio_bytes = data.opus if self.use_opus else data.pcm
        if not audio_bytes:
            return

        stats = self._ensure_user_stats(user)
        if stats.audio_chunk_count == 0:
            chunk_label = "Opus packet" if self.use_opus else "PCM frame"
            logger.info("First %s received from %s (%s)", chunk_label, stats.display_name, stats.user_id)

        stats.audio_chunk_count += 1
        frame = AudioFrame.new(user_id=user.id, pcm_bytes=audio_bytes)

        try:
            self.loop.call_soon_threadsafe(self._enqueue_frame, frame)
        except RuntimeError:
            logger.debug("Skipping audio frame because the event loop is no longer running.")

    @AudioSink.listener()
    def on_voice_member_speaking_start(self, member: discord.Member) -> None:
        """Record speaking-start events emitted by the receive extension."""
        if self._closed or member is None:
            return

        stats = self._ensure_user_stats(member)
        stats.speaking_start_count += 1
        logger.info("Speaking started for %s (%s)", stats.display_name, stats.user_id)

    @AudioSink.listener()
    def on_voice_member_speaking_stop(self, member: discord.Member) -> None:
        """Record speaking-stop events emitted by the receive extension."""
        if self._closed or member is None:
            return

        stats = self._ensure_user_stats(member)
        stats.speaking_stop_count += 1
        logger.info("Speaking stopped for %s (%s)", stats.display_name, stats.user_id)

    def cleanup(self) -> None:
        """Release sink resources. Safe to call more than once."""
        if self._closed:
            return

        self._closed = True
        logger.debug("DiscordAudioSink cleanup complete")

    @property
    def total_frames(self) -> int:
        """Return the total audio chunks recorded in this receive window."""
        return sum(stats.audio_chunk_count for stats in self._user_stats.values())

    @property
    def total_users(self) -> int:
        """Return the number of distinct users observed in this window."""
        return len(self._user_stats)

    def summary_lines(self) -> list[str]:
        """Build human-readable summary lines for the receive window."""
        if not self._user_stats:
            return ["No user activity detected."]

        lines: list[str] = []
        for stats in sorted(self._user_stats.values(), key=lambda item: item.display_name.lower()):
            lines.append(
                (
                    f"{stats.display_name} ({stats.user_id}): "
                    f"speaking starts={stats.speaking_start_count}, "
                    f"speaking stops={stats.speaking_stop_count}, "
                    f"audio chunks={stats.audio_chunk_count}"
                )
            )

        return lines

    def _ensure_user_stats(self, user: discord.abc.User) -> ReceivedUserStats:
        """Return the tracked stats entry for a Discord user, creating it if needed."""
        display_name = getattr(user, "display_name", None) or user.name
        stats = self._user_stats.get(user.id)

        if stats is None:
            stats = ReceivedUserStats(user_id=user.id, display_name=display_name)
            self._user_stats[user.id] = stats

        return stats

    def _enqueue_frame(self, frame: AudioFrame) -> None:
        """Push a frame into the async queue without blocking the reader thread."""
        try:
            self.audio_queue.put_nowait(frame)
        except asyncio.QueueFull:
            if not self._queue_full_logged:
                self._queue_full_logged = True
                logger.warning("Audio queue is full; dropping received frames.")
