"""Audio frame data models."""

from dataclasses import dataclass
import time


@dataclass
class AudioFrame:
    """Represents a chunk of audio received from a Discord user.
    
    Phase 2: Voice receive plumbing
    """

    user_id: int
    pcm_bytes: bytes
    sample_rate_hz: int
    channels: int
    timestamp_monotonic: float

    @classmethod
    def new(
        cls,
        user_id: int,
        pcm_bytes: bytes,
        sample_rate_hz: int = 48000,
        channels: int = 2,
    ) -> "AudioFrame":
        """Create a new AudioFrame with current monotonic timestamp.
        
        Args:
            user_id: Discord user ID
            pcm_bytes: Raw PCM audio data
            sample_rate_hz: Sample rate in Hz (48000 for Discord)
            channels: Number of channels (2 for stereo)
            
        Returns:
            AudioFrame with current timestamp
        """
        return cls(user_id, pcm_bytes, sample_rate_hz, channels, time.monotonic())
