"""Audio frame data models."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class AudioFrame:
    """Represents a chunk of audio received from a Discord user."""

    user_id: int
    username: str
    pcm_bytes: bytes
    sample_rate_hz: int
    channels: int
    timestamp_monotonic: float

    @classmethod
    def new(
        cls,
        user_id: int,
        username: str,
        pcm_bytes: bytes,
        sample_rate_hz: int = 48000,
        channels: int = 2,
    ) -> "AudioFrame":
        """Create a new AudioFrame with current monotonic timestamp.

        Args:
            user_id: Discord user ID
            username: Discord display name used for transcript attribution
            pcm_bytes: Raw PCM audio data
            sample_rate_hz: Sample rate in Hz (48000 for Discord)
            channels: Number of channels (2 for stereo)

        Returns:
            AudioFrame with current timestamp
        """
        return cls(user_id, username, pcm_bytes, sample_rate_hz, channels, time.monotonic())
