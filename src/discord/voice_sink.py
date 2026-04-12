"""Voice receive sink implementation for per-user audio capture."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from discord.ext.voice_recv import AudioSink, VoiceData
from discord.ext.voice_recv.opus import PacketDecoder
from discord.opus import Decoder, OpusError

import discord

from ..models import AudioFrame

logger = logging.getLogger(__name__)


def _install_safe_packet_decoder_guard(packet_decoder_cls: type = PacketDecoder) -> None:
    """
    Make discord-ext-voice-recv tolerate corrupted Opus packets in PCM mode.

    The library's built-in PCM path already handles jitter buffering, packet loss,
    and FEC. We keep that path for transcription and only guard against
    `OpusError` so one bad packet does not kill the router thread.
    """
    if getattr(packet_decoder_cls.pop_data, "__discord_audio_bot_safe__", False):
        return

    original_pop_data = packet_decoder_cls.pop_data

    def safe_pop_data(self, *, timeout: float = 0):
        try:
            return original_pop_data(self, timeout=timeout)
        except OpusError:
            last_error_log = getattr(self, "_discord_audio_bot_last_decode_error", 0.0)
            now = time.monotonic()
            if now - last_error_log >= 1.0:
                logger.warning(
                    "Skipping corrupted Opus packet for ssrc %s and resetting decoder.",
                    self.ssrc,
                )
                setattr(self, "_discord_audio_bot_last_decode_error", now)

            self._decoder = None if self.sink.wants_opus() else Decoder()
            return None

    safe_pop_data.__discord_audio_bot_safe__ = True
    packet_decoder_cls.pop_data = safe_pop_data


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

    Receive smoke mode defaults to Opus to validate receive without depending on
    PCM decode. Transcription mode uses PCM receive so downstream STT always gets
    real PCM bytes with user attribution.
    """

    def __init__(
        self,
        audio_queue: asyncio.Queue[AudioFrame],
        loop: asyncio.AbstractEventLoop,
        *,
        use_opus: bool = True,
        decode_opus: bool = False,
    ) -> None:
        """Initialize the sink with a target queue, event loop, and audio mode."""
        super().__init__()
        self.audio_queue = audio_queue
        self.loop = loop
        self.use_opus = use_opus
        self.decode_opus = decode_opus
        self._closed = False
        self._queue_full_logged = False
        self._user_stats: dict[int, ReceivedUserStats] = {}
        self._decoders: dict[int, Decoder] = {}
        _install_safe_packet_decoder_guard()
        mode = "Opus" if use_opus else "PCM"
        decode_mode = " with local decode" if decode_opus else ""
        logger.info("DiscordAudioSink initialized in %s mode%s", mode, decode_mode)

    def wants_opus(self) -> bool:
        """Tell discord-ext-voice-recv whether this sink wants raw Opus packets."""
        return self.use_opus

    def write(self, user: Optional[discord.User], data: VoiceData) -> None:
        """Receive one audio chunk from the extension and forward it safely."""
        if self._closed or user is None:
            return

        packet_bytes = data.opus if self.use_opus else data.pcm
        if not packet_bytes:
            return

        stats = self._ensure_user_stats(user)
        if stats.audio_chunk_count == 0:
            chunk_label = "Opus packet" if self.use_opus else "PCM frame"
            logger.info("First %s received from %s (%s)", chunk_label, stats.display_name, stats.user_id)

        audio_bytes = packet_bytes
        if self.decode_opus:
            audio_bytes = self._decode_opus_packet(data, user.id, packet_bytes)
            if not audio_bytes:
                return

        stats.audio_chunk_count += 1
        frame = AudioFrame.new(
            user_id=user.id,
            username=stats.display_name,
            pcm_bytes=audio_bytes,
        )

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
        self._decoders.clear()
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

    def _decode_opus_packet(
        self,
        data: VoiceData,
        user_id: int,
        packet_bytes: bytes,
    ) -> bytes | None:
        """Decode one Opus packet locally and tolerate decoder corruption."""
        decoder_key = getattr(getattr(data, "packet", None), "ssrc", None) or user_id
        decoder = self._decoders.get(decoder_key)
        if decoder is None:
            decoder = Decoder()
            self._decoders[decoder_key] = decoder

        try:
            return decoder.decode(packet_bytes, fec=False)
        except OpusError:
            logger.warning(
                "Skipping corrupted Opus packet for user %s on stream %s and resetting decoder.",
                user_id,
                decoder_key,
            )
            self._decoders[decoder_key] = Decoder()
            return None
